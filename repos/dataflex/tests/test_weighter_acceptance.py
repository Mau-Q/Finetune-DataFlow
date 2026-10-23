"""Independent loss/gradient contracts for single-device sample weighting."""
import unittest
import weakref
from types import SimpleNamespace
import torch
from dataflex.train.weighter.custom_weighter import CustomWeighter
from dataflex.train.weighter.loss_weighter import LossWeighter

class WeightMathTests(unittest.TestCase):
    def test_custom_uniform_is_sample_mean_with_equal_derivatives(self):
        x=torch.tensor([1.,3.],requires_grad=True)
        v=CustomWeighter().get_weighted_loss(x)
        torch.testing.assert_close(v,torch.tensor(2.))
        torch.testing.assert_close(torch.autograd.grad(v,x)[0],torch.tensor([.5,.5]))

    def test_linupper_coefficients_and_gradients_are_detached_weights(self):
        x=torch.tensor([1.,3.],requires_grad=True)
        v=LossWeighter(strategy='linupper').get_weighted_loss(x)
        expected=torch.softmax(torch.tensor([0.,1.]),dim=0)
        torch.testing.assert_close(v,(x*expected).sum())
        torch.testing.assert_close(torch.autograd.grad(v,x)[0],expected)
        one=torch.tensor([3.],requires_grad=True)
        torch.testing.assert_close(torch.autograd.grad(LossWeighter().get_weighted_loss(one),one)[0],torch.ones(1))

    def test_actual_training_step_scales_once_by_actual_accumulation(self):
        from contextlib import nullcontext
        from accelerate.utils import DistributedType
        for weighter,expected_weights in [(CustomWeighter(),None),(LossWeighter(),True)]:
            # Unequal valid answer lengths ensure this checks sample mean, not
            # accidental equivalence with model-wide token mean.
            m=torch.nn.Linear(2,3,bias=False)
            with torch.no_grad():m.weight.copy_(torch.tensor([[.2,-.3],[.1,.6],[-.4,.2]]))
            inputs={'input_ids':torch.tensor([[[1.,0.],[0.,1.],[1.,1.]],[[.4,.7],[.6,.2],[.1,.1]]]),'labels':torch.tensor([[-100,1,0],[-100,2,-100]])}
            output_refs=[]
            class Output:
                def __init__(self,logits,loss):self.logits,self.loss=logits,loss
            def compute(model,features,**kw):
                logits=model(features['input_ids']);raw=torch.nn.functional.cross_entropy(logits[:,:-1].reshape(-1,3),features['labels'][:,1:].reshape(-1),ignore_index=-100)
                output=Output(logits,raw);output_refs.append(weakref.ref(output));return raw,output
            def backward(value,**kwargs):
                self.assertIsNone(output_refs[-1](), 'Unused model output graph must be released before backward')
                value.backward()
            ctx=SimpleNamespace(optimizer=None,_prepare_inputs=lambda x:x,compute_loss_context_manager=nullcontext,compute_loss=compute,args=SimpleNamespace(local_rank=-1,torch_empty_cache_steps=None,n_gpu=1,gradient_accumulation_steps=4),state=SimpleNamespace(global_step=0),current_gradient_accumulation_steps=2,model_accepts_loss_kwargs=True,compute_loss_func=None,accelerator=SimpleNamespace(distributed_type=DistributedType.NO,backward=backward))
            logits=m(inputs['input_ids']);labels=inputs['labels']
            sample=torch.stack([torch.nn.functional.cross_entropy(logits[i,:-1],labels[i,1:],ignore_index=-100) for i in range(2)])
            if expected_weights:
                z=2*(sample.detach()-sample.detach().min())/(sample.detach().max()-sample.detach().min())-1
                weights=torch.softmax(torch.minimum(z+1,torch.ones_like(z)),0)
            else:weights=torch.tensor([.5,.5])
            expected=(sample*weights).sum()/2
            expected_gradient=torch.autograd.grad(expected,m.weight)[0]
            actual=weighter.training_step(ctx,m,inputs,num_items_in_batch=torch.tensor(3),use_weighter=True)
            torch.testing.assert_close(actual,expected.detach(),atol=1e-6,rtol=1e-5)
            torch.testing.assert_close(m.weight.grad,expected_gradient,atol=1e-6,rtol=1e-5)
if __name__=='__main__':unittest.main()
