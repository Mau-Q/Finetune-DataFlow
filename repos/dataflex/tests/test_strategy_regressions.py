"""CPU regression checks. Run with PYTHONPATH=src python -m unittest discover -s tests.

DoReMi trainer checks require the actual LLaMA-Factory installation and are
explicitly skipped on the lightweight Mac environment. No pretrained model,
network access or CUDA initialization is required.
"""
import importlib.util
import unittest
from types import SimpleNamespace

import numpy as np
import torch

from dataflex.core.registry import Registry, REGISTRY
from dataflex.train.mixer.odm_mixer import ODMMixer
from dataflex.utils.loss_utils import per_sample_loss_from_logits


class RegistryTests(unittest.TestCase):
    def test_config_kwargs_propagate_without_leaking_runtime(self):
        registry = Registry()

        @registry.register('test', 'component')
        class Component:
            def __init__(self, dataset, **kwargs):
                self.dataset, self.kwargs = dataset, kwargs

        obj = registry.build('test', 'component', runtime={'dataset': 'actual', 'eval_dataset': 'unused'},
                             cfg={'dataset': 'stale', 'reward_scale': 3.5})
        self.assertEqual(obj.dataset, 'actual')
        self.assertEqual(obj.kwargs, {'reward_scale': 3.5})

    def test_explicit_constructor_keeps_filtering_runtime(self):
        registry = Registry()

        @registry.register('test', 'plain')
        class Plain:
            def __init__(self, seed=0):
                self.seed = seed

        self.assertEqual(registry.build('test', 'plain', runtime={'dataset': object()}, cfg={'seed': 17}).seed, 17)


class LossTests(unittest.TestCase):
    def setUp(self):
        self.logits = torch.tensor([[[0., 2.], [1., -1.], [0., 0.]],
                                    [[2., 0.], [-1., 1.], [0., 0.]]], requires_grad=True)
        self.labels = torch.tensor([[-100, 1, 0], [-100, 0, -100]])

    def test_batch_invariance_and_mask(self):
        batched = per_sample_loss_from_logits(self.logits, self.labels)
        singles = torch.cat([per_sample_loss_from_logits(x[None], y[None])
                             for x, y in zip(self.logits, self.labels)])
        torch.testing.assert_close(batched, singles)
        self.assertFalse(batched.requires_grad)
        invalid = self.labels.clone(); invalid[0] = -100
        self.assertTrue(torch.isnan(per_sample_loss_from_logits(self.logits, invalid)[0]))

    def test_training_loss_keeps_gradient_and_label_smoothing(self):
        losses = per_sample_loss_from_logits(self.logits, self.labels, detach=False, label_smoothing=.1)
        independent = torch.stack([
            torch.nn.functional.cross_entropy(x[:-1].float(), y[1:], ignore_index=-100, label_smoothing=.1)
            for x, y in zip(self.logits, self.labels)
        ])
        torch.testing.assert_close(losses, independent)
        (losses * torch.tensor([.2, .8])).mean().backward()
        self.assertTrue(torch.isfinite(self.logits.grad).all())
        self.assertGreater(self.logits.grad.abs().sum().item(), 0)


class ODMTests(unittest.TestCase):
    def setUp(self):
        self.manager = SimpleNamespace(names=['a', 'b'], initial_proportions=[.5, .5])
        self.mixer = REGISTRY.build('mixer', 'odm', runtime={'mixture_manager': self.manager},
                                   cfg={'warmup_steps': 0, 'reward_scale': 2., 'min_exploration_rate': .02})

    def test_nondefault_settings_reach_real_mixer(self):
        self.assertEqual(self.mixer.reward_scale, 2.)
        self.assertEqual(self.mixer.min_exploration_rate, .02)

    def test_single_or_homogeneous_domain_feedback(self):
        for domain in [0, torch.tensor([0]), torch.tensor([0, 0])]:
            self.mixer.update_batch_info(3., domain)
            self.assertEqual(self.mixer.prev_batch_info, {'loss': 3., 'domain_id': 0})

    def test_ambiguous_or_invalid_feedback_is_rejected(self):
        for domain in [torch.tensor([0, 1]), [], -1, 2, .5]:
            with self.subTest(domain=domain), self.assertRaises(ValueError):
                self.mixer.update_batch_info(3., domain)
        with self.assertRaises(ValueError):
            self.mixer.update_batch_info(float('nan'), 0)

    def test_reward_and_normalized_policy(self):
        self.mixer.update_batch_info(3., 0)
        probs = self.mixer.mix(None, step_id=20)
        self.assertAlmostEqual(self.mixer.estimated_rewards[0], (1-.9)*(3.*2./.5))
        self.assertTrue(np.isfinite(probs).all())
        self.assertAlmostEqual(float(probs.sum()), 1.)
        self.assertGreater(float(probs[0]), float(probs[1]))


HAS_FACTORY = importlib.util.find_spec('llamafactory') is not None


@unittest.skipUnless(HAS_FACTORY, 'Actual LLaMA-Factory is only installed in the school training environment')
class DoReMiTrainerTests(unittest.TestCase):
    def setUp(self):
        from dataflex.train.trainer.mix_trainer import MixTrainer
        self.compute_loss = MixTrainer.compute_loss
        self.ctx = SimpleNamespace(
            mixer=SimpleNamespace(get_current_doremi_weights=lambda: [.2, .8]),
            finetuning_args=SimpleNamespace(static_mix=False),
            args=SimpleNamespace(label_smoothing_factor=0.), label_smoother=None,
            accelerator=SimpleNamespace(is_main_process=False),
        )

        class TinyModel(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.logits = torch.nn.Parameter(torch.tensor(
                    [[[0., 1.], [1., 0.], [0., 0.]], [[1., 0.], [0., 1.], [0., 0.]]]))

            def forward(self, input_ids, labels):
                return {'logits': self.logits, 'loss': self.logits.sum()*0+99.}

        self.model = TinyModel()
        self.inputs = {'input_ids': torch.zeros(2, 3, dtype=torch.long),
                       'labels': torch.tensor([[-100, 0, 1], [-100, 1, -100]]),
                       'domain_id': torch.tensor([0, 1])}

    def test_default_no_label_smoother_really_weights_gradients(self):
        loss = self.compute_loss(self.ctx, self.model, self.inputs)
        expected = (per_sample_loss_from_logits(self.model.logits, self.inputs['labels'], detach=False)
                    * torch.tensor([.2, .8])).mean()
        torch.testing.assert_close(loss, expected)
        actual_grad = torch.autograd.grad(loss, self.model.logits, retain_graph=True)[0]
        expected_grad = torch.autograd.grad(expected, self.model.logits)[0]
        torch.testing.assert_close(actual_grad, expected_grad)
        self.assertIn('domain_id', self.inputs)
        self.assertIn('labels', self.inputs)

    def test_smoothing_is_applied_per_sample(self):
        self.ctx.args.label_smoothing_factor = .1
        self.ctx.label_smoother = object()
        actual = self.compute_loss(self.ctx, self.model, self.inputs)
        expected = torch.stack([
            torch.nn.functional.cross_entropy(x[:-1], y[1:], ignore_index=-100, label_smoothing=.1)
            for x, y in zip(self.model.logits, self.inputs['labels'])
        ])
        torch.testing.assert_close(actual, (expected*torch.tensor([.2, .8])).mean())

    def test_missing_metadata_does_not_silently_disable_weighting(self):
        for key in ['domain_id', 'labels']:
            inputs = {k: v for k, v in self.inputs.items() if k != key}
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.compute_loss(self.ctx, self.model, inputs)

    def test_scalar_model_loss_is_not_a_valid_fallback(self):
        model = lambda **kwargs: {'loss': torch.tensor(99., requires_grad=True)}
        with self.assertRaises(ValueError):
            self.compute_loss(self.ctx, model, self.inputs)

    def test_invalid_domains_or_unsupervised_rows_fail(self):
        for ids in [torch.tensor([0]), torch.tensor([0, 5])]:
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                self.compute_loss(self.ctx, self.model, dict(self.inputs, domain_id=ids))
        labels = self.inputs['labels'].clone(); labels[0] = -100
        with self.assertRaises(ValueError):
            self.compute_loss(self.ctx, self.model, dict(self.inputs, labels=labels))


if __name__ == '__main__':
    unittest.main()
