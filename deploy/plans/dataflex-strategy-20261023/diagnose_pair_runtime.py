"""Isolated real-CLI diagnostic: dropout/checkpoint traces and exact LoRA gradients.

Writes into new diagnostic attempts; never changes existing G06/G07 pointers.
All hooks return None, consume no RNG and save read-only CPU copies.
"""
import argparse
import functools
import hashlib
import json
import os
from pathlib import Path

import torch
from safetensors.torch import save_file
from transformers import TrainerCallback
import observed_run as observer


def tensor_signature(value):
    sample = value.detach().reshape(-1)[:65536].contiguous().cpu()
    return {'shape': list(value.shape), 'dtype': str(value.dtype),
            'prefix_elements': sample.numel(),
            'sha256': hashlib.sha256(sample.view(torch.uint8).numpy().tobytes()).hexdigest(),
            'zero_count': int((sample == 0).sum())}


def rng_signature():
    return {'cpu': hashlib.sha256(torch.get_rng_state().numpy().tobytes()).hexdigest(),
            'cuda': hashlib.sha256(torch.cuda.get_rng_state().numpy().tobytes()).hexdigest()}


def enable_diagnostics(cls, folder, trace_dropout, hash_base, trace_layers=False):
    current = original_install(cls, folder)
    def emit(kind, **fields):
        observer.emit(folder/(kind+'.jsonl'), fields)
    class DiagnosticCallback(TrainerCallback):
        def on_train_begin(self, args, state, control, **kwargs):
            model = kwargs['model']
            checkpoints = []
            for name, module in model.named_modules():
                if getattr(module, 'gradient_checkpointing', False):
                    func = getattr(module, '_gradient_checkpointing_func', None)
                    wrapped = getattr(func, '__wrapped__', None)
                    checkpoints.append({'module': name, 'function': str(func), 'wrapped': str(wrapped),
                                        'wrapped_keywords': str(getattr(wrapped, 'keywords', None))})
            emit('diagnostic-runtime', checkpoints=checkpoints[:3],
                 deterministic=torch.are_deterministic_algorithms_enabled(),
                 allow_tf32_matmul=torch.backends.cuda.matmul.allow_tf32,
                 allow_tf32_cudnn=torch.backends.cudnn.allow_tf32,
                 script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                 sdp_backends={name: getattr(torch.backends.cuda,name+'_sdp_enabled')()
                               for name in ['flash','math','mem_efficient','cudnn']})
            if hash_base:
                hashes = {}
                def digest(value):
                    value = value.detach().cpu().contiguous().reshape(-1).view(torch.uint8)
                    return hashlib.sha256(memoryview(value.numpy())).hexdigest()
                def quantization_state(prefix, state):
                    for key,value in vars(state).items():
                        if torch.is_tensor(value): hashes[prefix+'.'+key] = digest(value)
                        elif key == 'state2' and value is not None: quantization_state(prefix+'.state2',value)
                for name,parameter in model.named_parameters():
                    hashes[name] = digest(parameter)
                    if getattr(parameter,'quant_state',None) is not None:
                        quantization_state(name+'.quant_state',parameter.quant_state)
                for name,buffer in model.named_buffers():hashes['buffer:'+name]=digest(buffer)
                (folder/'initial-model-hashes.json').write_text(json.dumps(hashes,indent=2))
            def attention_hook(module, inputs, output):
                if current.get('micro') != 1 or not torch.is_grad_enabled(): return
                tensor = output[0] if isinstance(output,tuple) else output
                queue=[tensor.grad_fn];seen=set();kinds=set()
                while queue and len(seen)<1000:
                    node=queue.pop()
                    if node is None or node in seen: continue
                    seen.add(node);kinds.add(type(node).__name__)
                    queue.extend(n for n,_ in node.next_functions)
                emit('diagnostic-attention', micro=current['micro'], grad_nodes=sorted(kinds))
            for name,module in model.named_modules():
                if name.endswith('.layers.3.self_attn'): module.register_forward_hook(attention_hook)
            for part in ['lora_A', 'lora_B']:
                name, parameter = next((n,p) for n,p in model.named_parameters() if p.requires_grad and part in n)
                def gradient_hook(gradient, name=name):
                    micro = current['micro']
                    if micro <= 8:
                        save_file({'gradient': gradient.detach().cpu().contiguous()},
                                  str(folder/('gradient-%02d-%s.safetensors' % (micro, 'A' if 'lora_A' in name else 'B'))))
                        emit('diagnostic-gradient', micro=micro, parameter=name,
                             tensor=tensor_signature(gradient), rng=rng_signature())
                    return None
                parameter.register_hook(gradient_hook)
            if trace_layers:
                def full_signature(value):
                    value=value.detach().cpu().contiguous()
                    return {'shape':list(value.shape),'dtype':str(value.dtype),
                            'sha256':hashlib.sha256(value.reshape(-1).view(torch.uint8).numpy().tobytes()).hexdigest()}
                def layer_hook(module, inputs, output, name):
                    if current.get('micro') != 1:return
                    tensor=output[0] if isinstance(output,tuple) else output
                    if not torch.is_tensor(tensor):return
                    emit('diagnostic-layers',module=name,grad_enabled=torch.is_grad_enabled(),
                         input=full_signature(inputs[0]) if inputs and torch.is_tensor(inputs[0]) else None,
                         output=full_signature(tensor))
                for name,module in model.named_modules():
                    if ('.layers.' in name and name.rsplit('.',1)[-1].isdigit()) or ('.layers.0.' in name and not list(module.children())):
                        module.register_forward_hook(functools.partial(layer_hook,name=name))
            if trace_dropout:
                for name, module in model.named_modules():
                    if isinstance(module, torch.nn.Dropout) and '.layers.0.' in name:
                        def before(module, inputs, name=name):
                            if current.get('micro', 999) <= 8:
                                emit('diagnostic-dropout', phase='before', micro=current['micro'], module=name,
                                     grad_enabled=torch.is_grad_enabled(), p=module.p,
                                     input=tensor_signature(inputs[0]), rng=rng_signature())
                        def after(module, inputs, output, name=name):
                            if current.get('micro', 999) <= 8:
                                emit('diagnostic-dropout', phase='after', micro=current['micro'], module=name,
                                     grad_enabled=torch.is_grad_enabled(), output=tensor_signature(output), rng=rng_signature())
                        module.register_forward_pre_hook(before)
                        module.register_forward_hook(after)
    old_init = cls.__init__
    @functools.wraps(old_init)
    def init(self, *args, **kwargs):
        old_init(self, *args, **kwargs)
        self.add_callback(DiagnosticCallback())
    cls.__init__ = init
    return current


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--trace-dropout', action='store_true')
    parser.add_argument('--hash-base', action='store_true')
    parser.add_argument('--trace-layers', action='store_true')
    parser.add_argument('--strict-determinism', action='store_true')
    parser.add_argument('--math-sdpa', action='store_true')
    args = parser.parse_args()
    if args.strict_determinism:
        os.environ['CUBLAS_WORKSPACE_CONFIG']=':4096:8'
        torch.use_deterministic_algorithms(True)
        torch.backends.cudnn.deterministic=True
        torch.backends.cudnn.benchmark=False
    if args.math_sdpa:
        torch.backends.cuda.enable_flash_sdp(False)
        torch.backends.cuda.enable_mem_efficient_sdp(False)
        torch.backends.cuda.enable_cudnn_sdp(False)
        torch.backends.cuda.enable_math_sdp(True)
    original_install = observer.install
    observer.install = lambda cls, folder: enable_diagnostics(cls, folder, args.trace_dropout,args.hash_base,args.trace_layers)
    observer.train(args.config, args.folder)
