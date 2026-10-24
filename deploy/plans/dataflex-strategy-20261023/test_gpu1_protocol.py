"""CPU contracts for early policy setup; actual GPU acceptance is separate."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import extended_execution_policy as policy
import observed_run as observer
import gpu1_entry


class ExtendedEntryContracts(unittest.TestCase):
    def test_training_installs_extended_policy_before_cuda_allocator(self):
        order = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); config = root/'train.yaml'
            config.write_text('full_determinism: false\n')
            (root/'paired-control-attempt1.json').write_text(json.dumps({'deterministic_execution': policy.PROTOCOL}))
            def allocator(*args):
                order.append('cuda_allocator')
                raise RuntimeError('CPU boundary')
            with patch.object(policy, 'install', side_effect=lambda: order.append('fla_policy')), patch.object(policy, 'persist'), patch.object(observer.torch.cuda, 'set_per_process_memory_fraction', side_effect=allocator):
                with self.assertRaisesRegex(RuntimeError, 'CPU boundary'):
                    observer.train(config, root/'attempt1')
        self.assertEqual(order, ['fla_policy', 'cuda_allocator'])

    def test_generation_prepares_same_protocol_before_model_entry(self):
        order = []
        def model_entry(name):
            order.append(('model_entry', name))
            raise RuntimeError('CPU boundary')
        with tempfile.TemporaryDirectory() as directory:
            evaluator = SimpleNamespace(main=model_entry)
            with patch.dict(sys.modules, {'evaluate_frozen': evaluator}), patch.object(observer, 'prepare_reproducibility', side_effect=lambda cfg, protocol: order.append(('policy', protocol))):
                with self.assertRaisesRegex(RuntimeError, 'CPU boundary'):
                    gpu1_entry.main('evaluate', Path(directory), 'BASE', 'attempt1')
        self.assertEqual(order, [('policy', policy.PROTOCOL), ('model_entry', 'BASE')])

    def test_protocol_rejects_unknown_name(self):
        with self.assertRaisesRegex(ValueError, 'Unknown'):
            observer.prepare_reproducibility({}, 'unknown')


if __name__ == '__main__':
    unittest.main()
