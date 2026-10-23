"""CPU checks: compile-only selection, unsupported candidates, non-FLA isolation."""
import hashlib
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import fla_compile_policy as policy


class CompilePolicyContracts(unittest.TestCase):
    def run_case(self, module_name, unsupported=False):
        class Unsupported(Exception):
            pass
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'autotuner.py';source.write_text('source fixture')
            original = Mock(return_value=[7, 7, 7])
            class Autotuner:
                _bench = original
            triton = ModuleType('triton');runtime = ModuleType('triton.runtime')
            autotuner = ModuleType('triton.runtime.autotuner');autotuner.__file__ = str(source)
            autotuner.Autotuner = Autotuner
            runtime.autotuner = autotuner;triton.runtime = runtime
            compiler = ModuleType('triton.compiler');triton.compiler = compiler
            ce = ModuleType('triton.compiler.errors');ce.CompileTimeAssertionFailure = Unsupported
            re = ModuleType('triton.runtime.errors');re.OutOfResources = Unsupported
            compiler.errors = ce;runtime.errors = re
            modules = {m.__name__: m for m in [triton, runtime, autotuner, compiler, ce, re]}
            config = SimpleNamespace(kwargs={}, num_warps=4, num_stages=2,
                                     all_kwargs=lambda: {'num_warps': 4, 'num_stages': 2})
            compile_call = Mock(side_effect=Unsupported() if unsupported else None)
            tuner = Autotuner()
            tuner.base_fn = SimpleNamespace(__module__=module_name, __name__='kernel')
            tuner.fn = SimpleNamespace(run=compile_call)
            tuner.configs = [config]
            with patch.dict(sys.modules, modules), patch.object(policy, 'AUTOTUNER_SHA256', hashlib.sha256(source.read_bytes()).hexdigest()):
                receipt, calls = policy.install()
                result = tuner._bench('tensor-placeholder', config=config, grid=(1,))
            return result, calls, compile_call, original

    def test_fla_candidates_are_compiled_without_timed_execution(self):
        result, calls, compile_call, original = self.run_case('fla.ops.fixture')
        self.assertEqual(result, [0, 0, 0])
        self.assertTrue(compile_call.call_args.kwargs['warmup'])
        self.assertTrue(calls[0]['compile_supported'])
        original.assert_not_called()

    def test_unsupported_candidate_retains_infinite_rank(self):
        result, calls, _, original = self.run_case('fla.ops.fixture', unsupported=True)
        self.assertTrue(all(x == float('inf') for x in result))
        self.assertFalse(calls[0]['compile_supported'])
        original.assert_not_called()

    def test_non_fla_autotuner_keeps_original_behavior(self):
        result, calls, compile_call, original = self.run_case('other_library.kernel')
        self.assertEqual(result, [7, 7, 7])
        self.assertEqual(calls, [])
        compile_call.assert_not_called()
        original.assert_called_once()


if __name__ == '__main__':
    unittest.main()
