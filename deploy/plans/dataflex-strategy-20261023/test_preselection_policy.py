"""CPU contracts for the task-scoped launch policy, not GPU reproducibility proof."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import fla_numerical_policy as policy


class PolicyContracts(unittest.TestCase):
    def fixture(self, source):
        candidate = SimpleNamespace(kwargs={'BK': 64, 'BV': 64}, num_warps=4, num_stages=3)
        other = SimpleNamespace(kwargs={'BK': 128, 'BV': 128}, num_warps=8, num_stages=3)
        tuner = SimpleNamespace(configs=[other, candidate], cache={'old': 'entry'}, cache_results=True)
        module = SimpleNamespace(__file__=str(source), chunk_fwd_kernel_o=SimpleNamespace(fn=tuner))
        return module, tuner, candidate

    def test_selects_single_candidate_and_clears_only_in_memory_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'kernel.py';source.write_text('source fixture')
            module, tuner, candidate = self.fixture(source)
            before = source.read_bytes()
            with patch.object(policy, 'CHUNK_O_SHA256', hashlib.sha256(before).hexdigest()):
                result = policy.pin_chunk_o(module)
                self.assertEqual(tuner.configs, [candidate])
                self.assertEqual(tuner.cache, {})
                self.assertFalse(tuner.cache_results)
                self.assertEqual(result['candidate_count'], 1)
                self.assertEqual(source.read_bytes(), before)
                self.assertEqual(policy.pin_chunk_o(module), result)

    def test_changed_source_is_rejected_before_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'kernel.py';source.write_text('different source')
            module, tuner, _ = self.fixture(source)
            with self.assertRaisesRegex(ValueError, 'source changed'):
                policy.pin_chunk_o(module)
            self.assertEqual(len(tuner.configs), 2)
            self.assertTrue(tuner.cache_results)
            self.assertEqual(tuner.cache, {'old': 'entry'})

    def test_ambiguous_candidate_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'kernel.py';source.write_text('source fixture')
            module, tuner, candidate = self.fixture(source)
            tuner.configs.append(candidate)
            with patch.object(policy, 'CHUNK_O_SHA256', hashlib.sha256(source.read_bytes()).hexdigest()):
                with self.assertRaisesRegex(ValueError, 'exactly one'):
                    policy.pin_chunk_o(module)
            self.assertTrue(tuner.cache_results)

    def test_combined_policy_pins_gated_norm_forward_and_backward(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'kernel.py';source.write_text('source fixture')
            chunk, _, _ = self.fixture(source)
            def tuner():
                candidate = SimpleNamespace(kwargs={'BT': 16}, num_warps=4, num_stages=2)
                return SimpleNamespace(fn=SimpleNamespace(configs=[candidate], cache={'old': 'entry'}, cache_results=True))
            norm = SimpleNamespace(__file__=str(source),
                                   layer_norm_gated_fwd_kernel=tuner(), layer_norm_gated_bwd_kernel=tuner())
            modules = {'fla.ops.common.chunk_o': chunk, 'fla.modules.fused_norm_gate': norm}
            sha = hashlib.sha256(source.read_bytes()).hexdigest()
            with patch.object(policy, 'CHUNK_O_SHA256', sha), patch.object(policy, 'NORM_SHA256', sha), patch.object(policy.importlib, 'import_module', side_effect=modules.__getitem__):
                result = policy.pin_fla_attention()
            self.assertEqual(result['policy'], 'fla-linear-fixed-v2')
            self.assertEqual(len(result['kernels']), 3)
            for name in ['layer_norm_gated_fwd_kernel', 'layer_norm_gated_bwd_kernel']:
                self.assertFalse(getattr(norm, name).fn.cache_results)
                self.assertEqual(getattr(norm, name).fn.cache, {})


if __name__ == '__main__':
    unittest.main()
