"""Offline fixtures verify launch/evaluation bookkeeping, never GPU acceptance."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import sys
from types import SimpleNamespace
from unittest.mock import patch

import yaml

HERE = Path(__file__).parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SUITE = load('run_core8_suite')
EVAL = load('evaluate_frozen')
CONFIG = load('configure_execution')
MATERIALIZE = load('materialize_configs')
AUDIT = load('audit_observations')


class ReproducibilityContracts(unittest.TestCase):
    def test_explicit_protocol_rejects_hf_override_and_sets_cuda_policy(self):
        observer = load('observed_run')
        with self.assertRaisesRegex(ValueError, 'overrides'):
            observer.prepare_reproducibility({'full_determinism': True}, 'torch-math-cublas4096-v2')
        with patch.dict(observer.os.environ, {'CUDA_LAUNCH_BLOCKING':'1'}), observer.torch.backends.cuda.sdp_kernel(enable_flash=True,enable_math=True,enable_mem_efficient=True,enable_cudnn=True), patch.object(observer.torch, 'use_deterministic_algorithms') as enable, patch.object(observer.torch.backends, 'cudnn', SimpleNamespace(deterministic=False,benchmark=True)):
            observer.prepare_reproducibility({}, 'torch-math-cublas4096-v2')
            enable.assert_called_once_with(True)
            self.assertEqual(observer.os.environ['CUBLAS_WORKSPACE_CONFIG'], ':4096:8')
            self.assertNotIn('CUDA_LAUNCH_BLOCKING', observer.os.environ)
            self.assertTrue(observer.torch.backends.cudnn.deterministic)
            self.assertFalse(observer.torch.backends.cudnn.benchmark)
            self.assertTrue(observer.torch.backends.cuda.math_sdp_enabled())
            self.assertFalse(observer.torch.backends.cuda.flash_sdp_enabled())
            self.assertFalse(observer.torch.backends.cuda.mem_efficient_sdp_enabled())
            self.assertFalse(observer.torch.backends.cuda.cudnn_sdp_enabled())

    def test_full_determinism_is_explicit_and_uses_configured_seed(self):
        from unittest.mock import Mock
        observer = load('observed_run')
        helper = Mock()
        with patch.dict(sys.modules, {'transformers.trainer_utils': SimpleNamespace(enable_full_determinism=helper)}):
            observer.prepare_reproducibility({'seed': 17})
            helper.assert_not_called()
            observer.prepare_reproducibility({'seed': 17, 'full_determinism': True})
            helper.assert_called_once_with(17)

    def test_reproducibility_is_prepared_before_cuda_allocator(self):
        observer = load('observed_run')
        order = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root/'config.yaml'
            config.write_text('full_determinism: false\nseed: 17\n')
            (root/'paired-control-attempt1.json').write_text(json.dumps({'deterministic_execution':'torch-math-cublas4096-v2'}))
            def allocator(*args):
                order.append('cuda')
                raise RuntimeError('Intentional CPU-only stop before CUDA initialization')
            with patch.object(observer, 'prepare_reproducibility', side_effect=lambda cfg,protocol=None: order.append(('prepare',cfg['seed'],protocol))), patch.object(observer.torch.cuda, 'set_per_process_memory_fraction', side_effect=allocator):
                with self.assertRaisesRegex(RuntimeError, 'Intentional CPU-only'):
                    observer.train(config,root/'attempt1')
        self.assertEqual(order,[('prepare',17,'torch-math-cublas4096-v2'),'cuda'])


class ConfigContracts(unittest.TestCase):
    def test_attempt_caches_and_gate_eval_binding(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'plan'
            MATERIALIZE.materialize(root, str(root))
            (root / 'data-manifest.json').write_text(json.dumps({'tasks': ['a', 'b', 'c', 'd']}))
            original = (root / 'G02/train.yaml').read_bytes()
            CONFIG.configure(root)
            self.assertEqual((root / 'G02/train.yaml').read_bytes(), original)
            config = yaml.safe_load((root / 'G02/execution-v2.yaml').read_text())
            components = yaml.safe_load(Path(config['components_cfg_file']).read_text())
            self.assertEqual(config['dataset'], 'a,b,c,d')
            self.assertEqual(components['selectors']['loss']['params']['cache_dir'], str(root / 'G02/attempt1/strategy-cache'))
            for batch in [1, 2]:
                gate = yaml.safe_load((root / f'GATE-B{batch}/train.yaml').read_text())
                self.assertIsNone(gate['eval_dataset'])
                self.assertFalse(gate['do_eval'])
                self.assertEqual(gate['per_device_train_batch_size'] * gate['gradient_accumulation_steps'], 4)
            self.assertEqual(yaml.safe_load((root / 'GATE-B2/train.yaml').read_text())['train_type'], 'dynamic_weight')
            before = (root / 'G02/execution-v2.yaml').read_bytes()
            with self.assertRaises(FileExistsError):
                CONFIG.configure(root)
            self.assertEqual((root / 'G02/execution-v2.yaml').read_bytes(), before)

    def test_v2_can_coexist_with_earlier_execution_config(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'plan'
            MATERIALIZE.materialize(root, str(root))
            (root / 'data-manifest.json').write_text(json.dumps({'tasks': ['a', 'b', 'c', 'd']}))
            old = root / 'G00/execution.yaml'
            old.write_text('prior evidence\n')
            CONFIG.configure(root, include_initial_gates=False)
            self.assertEqual(old.read_text(), 'prior evidence\n')
            self.assertTrue((root / 'G00/execution-v2.yaml').exists())


class SuiteContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def fixture(self):
        (self.root / 'data-manifest.json').write_text('frozen fixture')
        for batch in [1, 2]:
            name = f'GATE2-B{batch}'
            folder = self.root / name / 'attempt2'
            (folder / 'output').mkdir(parents=True)
            (folder.parent / 'successful-attempt.json').write_text(json.dumps({'attempt': 'attempt2', 'observation_dir': f'/runs/strategy-20261023/{name}/attempt2'}))
            (folder / 'audit.json').write_text(json.dumps({'status': 'MECHANISM_OBSERVED', 'name': name, 'source_counts': {'a': 2, 'b': 2, 'c': 2, 'd': 2}, 'supervised_max': 286, 'length_max': 1024, 'optimizer_steps': 2}))
            adapter = folder / 'output/adapter_model.safetensors'
            adapter.write_bytes(b'fixture, not real adapter')
            evaluation = self.root / 'evaluation' / name
            evaluation.mkdir(parents=True)
            (evaluation / 'metrics.json').write_text(json.dumps({'model': name, 'n': 2, 'generation': {'prompt_method': 'hf_native_chat_template_enable_thinking_false'}, 'reasoning_tag_outputs': 0, 'empty_outputs': 0, 'adapter_reloaded': True, 'data_manifest_sha256': hashlib.sha256((self.root / 'data-manifest.json').read_bytes()).hexdigest(), 'adapter_sha256': hashlib.sha256(adapter.read_bytes()).hexdigest()}))
        score = self.root / 'evaluation/GATE2-B2/score-batch-check.json'
        score.write_text(json.dumps({'single': [1., 2., 3., 4.], 'batch2': [1.001, 2., 3., 4.]}))
        return score

    def test_container_pointer_maps_to_correct_host_attempt(self):
        self.fixture()
        self.assertEqual(SUITE.successful_folder('GATE2-B1', self.root), self.root / 'GATE2-B1/attempt2')
        SUITE.require_gates(self.root)

    def test_core_refuses_to_launch_before_gate_evidence(self):
        with patch.object(SUITE, 'HOST_RUN', self.root), patch.object(SUITE, 'execute') as execute, patch.object(SUITE, 'free_check') as free:
            with self.assertRaises(FileNotFoundError):
                SUITE.main('core')
            execute.assert_not_called()
            free.assert_not_called()

    def test_changed_adapter_invalidates_old_reload(self):
        self.fixture()
        (self.root / 'GATE2-B1/attempt2/output/adapter_model.safetensors').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'Reload'):
            SUITE.require_gates(self.root)

    def test_nan_missing_or_inconsistent_scores_do_not_pass(self):
        path = self.fixture()
        for values in [[float('nan'), 2., 3., 4.], [1.], [1., 2., 3., 5.]]:
            with self.subTest(values=values):
                path.write_text(json.dumps({'single': [1., 2., 3., 4.], 'batch2': values}))
                with self.assertRaises(ValueError):
                    SUITE.require_gates(self.root)

    def test_evaluation_attempt_pointer_preserves_prior_outputs(self):
        self.fixture()
        base = self.root / 'evaluation/GATE2-B1'
        (base / 'attempt2').mkdir()
        (base / 'successful-evaluation.json').write_text(json.dumps({'attempt': 'attempt2'}))
        self.assertEqual(SUITE.evaluation_folder('GATE2-B1', self.root), base / 'attempt2')
        self.assertTrue((base / 'metrics.json').exists())

    def test_changed_frozen_data_invalidates_evaluation(self):
        self.fixture()
        (self.root / 'data-manifest.json').write_text('changed fixture')
        with self.assertRaisesRegex(ValueError, 'data identity'):
            SUITE.require_evaluation('GATE2-B1', 2, self.root)

    def test_malicious_attempt_path_is_rejected(self):
        self.fixture()
        (self.root / 'GATE2-B1/successful-attempt.json').write_text(json.dumps({'attempt': '../other'}))
        with self.assertRaises(ValueError):
            SUITE.successful_folder('GATE2-B1', self.root)

    def test_old_weight_audit_cannot_substitute_for_paired_control(self):
        folder = self.root / 'G07/attempt1'
        folder.mkdir(parents=True)
        (folder.parent / 'successful-attempt.json').write_text(json.dumps({'attempt': 'attempt1'}))
        path = folder / 'audit.json'
        audit = {'status': 'MECHANISM_OBSERVED', 'name': 'G07'}
        path.write_text(json.dumps(audit))
        with self.assertRaisesRegex(ValueError, 'initialization'):
            SUITE.require_mechanism('G07', self.root)
        audit['paired_control'] = {'initial_adapter_tensor_sha256': 'fixture', 'snapshot_sha256': 'fixture',
                                   'micro_rng_seed_base': 420000}
        path.write_text(json.dumps(audit))
        with self.assertRaisesRegex(ValueError, 'gradient'):
            SUITE.require_mechanism('G07', self.root)
        audit['paired_control']['first_weighted_gradient_norms'] = {'fixture': {'uniform': 1., 'linupper': 2.}}
        path.write_text(json.dumps(audit))
        self.assertEqual(SUITE.require_mechanism('G07', self.root)['name'], 'G07')
        audit['paired_control']['trajectory_status'] = 'INCONCLUSIVE_WARMUP_MISMATCH'
        path.write_text(json.dumps(audit))
        with self.assertRaisesRegex(ValueError, 'separate same-forward'):
            SUITE.require_mechanism('G07', self.root)
        audit['paired_control']['same_forward_diagnostic'] = {'status': 'SAME_FORWARD_WEIGHT_GRADIENT_VERIFIED'}
        path.write_text(json.dumps(audit))
        self.assertEqual(SUITE.require_mechanism('G07', self.root)['paired_control']['trajectory_status'],
                         'INCONCLUSIVE_WARMUP_MISMATCH')


class DeltaContract(unittest.TestCase):
    def test_negative_delta_empty_window_has_reproducible_uniform_fallback(self):
        import torch
        indices, window = AUDIT.expected_delta_indices([1.]*256,[2.]*256,9,2)
        self.assertLessEqual(window[1],window[0])
        generator=torch.Generator().manual_seed(42+9)
        expected=torch.multinomial(torch.full((256,),1/256),20,replacement=False,generator=generator).tolist()
        self.assertEqual(indices,expected)


class GenerationPromptContract(unittest.TestCase):
    def test_native_no_think_uses_only_user_input(self):
        class Tokenizer:
            def apply_chat_template(self,messages,**kwargs):
                self.messages,self.kwargs=messages,kwargs
                return 'assistant\n<think>\n\n</think>\n\n'
            def encode(self,text,**kwargs):return [1,2]
        tokenizer=Tokenizer()
        self.assertEqual(EVAL.generation_prompt(tokenizer,'question only'),[1,2])
        self.assertEqual(tokenizer.messages,[{'role':'user','content':'question only'}])
        self.assertFalse(tokenizer.kwargs['enable_thinking'])

    def test_missing_native_no_think_prefill_is_rejected(self):
        class Tokenizer:
            def apply_chat_template(self,*args,**kwargs):return 'assistant\n'
        with self.assertRaises(ValueError):EVAL.generation_prompt(Tokenizer(),'q')


class MetricContracts(unittest.TestCase):
    def test_qa_normalization_and_partial_answer(self):
        self.assertEqual(EVAL.qa('The protein.', 'protein'), {'em': 1, 'token_f1': 1.})
        self.assertAlmostEqual(EVAL.qa('protein', 'protein complex')['token_f1'], 2/3)
        self.assertEqual(EVAL.qa('', 'protein')['token_f1'], 0.)

    def test_ner_invalid_json_remains_in_denominator(self):
        rows = [{'task': 'genia_ner', 'prediction': '{"Protein":["Rex"]}', 'reference': '{"Protein":["Rex"]}', 'cap_hit': False},
                {'task': 'genia_ner', 'prediction': 'not json', 'reference': '{"Protein":["Rex"]}', 'cap_hit': True}]
        result = EVAL.metrics(rows)['genia_ner']
        self.assertEqual(result['json_success'], .5)
        self.assertEqual(result['generation_cap_hits'], 1)
        self.assertEqual((result['tp'], result['fp'], result['fn']), (1, 0, 1))
        self.assertAlmostEqual(result['entity_exact_micro_f1'], 2/3)
        self.assertEqual(result['entity_exact_macro_sample_f1'], .5)
        self.assertEqual(result['successful_parse_subset_entity_micro_f1'], 1.)

    def test_wrong_entity_type_is_not_a_match(self):
        self.assertFalse(EVAL.ner('{"DNA":["Rex"]}') & EVAL.ner('{"Protein":["Rex"]}'))
        with self.assertRaises(ValueError):
            EVAL.ner('{"Protein":"Rex"}')

    def test_classification_invalid_answer_is_counted(self):
        rows = [{'task': 'scicite_classification', 'prediction': 'Background', 'reference': 'Background', 'cap_hit': False},
                {'task': 'scicite_classification', 'prediction': 'explanation without label', 'reference': 'Method', 'cap_hit': False}]
        result = EVAL.metrics(rows)['scicite_classification']
        self.assertEqual(result['accuracy'], .5)
        self.assertEqual(result['invalid_labels'], 1)

    def test_rouge_l_is_explicit_lcs_f1(self):
        self.assertEqual(EVAL.rouge_l('A B', 'a b'), 1.)
        self.assertAlmostEqual(EVAL.rouge_l('a b c', 'a c'), 4/5)
        self.assertEqual(EVAL.rouge_l('', 'a'), 0.)


@unittest.skipUnless(importlib.util.find_spec('peft') is not None, 'Actual PEFT callback check runs on school')
class PairedInitializationContracts(unittest.TestCase):
    def test_callback_preserves_trainer_control_and_state_and_restores_all_adapter_tensors(self):
        import torch
        from types import SimpleNamespace
        from peft import LoraConfig, get_peft_model
        observer = load('observed_run')
        class Tiny(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.linear = torch.nn.Linear(3, 2)
            def forward(self, x):
                return self.linear(x)
        class Trainer:
            def __init__(self, model):
                self.model = model
                self.finetuning_args = SimpleNamespace(lora_dropout=.05)
                self.accelerator = SimpleNamespace(backward=lambda value, **kw: None)
                self.callbacks = []
            def add_callback(self, callback):
                self.callbacks.append(callback)
            def compute_loss(self, *args, **kwargs):
                raise AssertionError('This CPU check must not train')
            def training_step(self, *args, **kwargs):
                raise AssertionError('This CPU check must not train')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'data').mkdir()
            (root / 'data/token-map.json').write_text('[]')
            observer.ROOT = root
            receipts = []
            for name, role in [('capture', 'capture'), ('restore', 'restore')]:
                folder = root / name / 'attempt1'
                folder.mkdir(parents=True)
                control = {'role': role, 'initial_adapter': str(root / 'shared/adapter.safetensors'),
                           'micro_rng_seed_base': 420000, 'lora_dropout': .05}
                (folder.parent / 'paired-control-attempt1.json').write_text(json.dumps(control))
                model = get_peft_model(Tiny(), LoraConfig(r=2, lora_alpha=4, lora_dropout=.05, target_modules=['linear']))
                # A fresh class avoids one wrapped callback leaking into the other.
                trainer_class = type('Trainer' + name, (Trainer,), {})
                observer.install(trainer_class, folder)
                trainer = trainer_class(model)
                state = SimpleNamespace(max_steps=2, global_step=0)
                callback_control = SimpleNamespace(should_training_stop=False)
                args = SimpleNamespace(max_steps=2, gradient_accumulation_steps=2,
                                       remove_unused_columns=False, train_sampling_strategy='random')
                trainer.callbacks[0].on_train_begin(args, state, callback_control, model=model,
                                                    lr_scheduler=SimpleNamespace(state_dict=lambda: {}))
                receipt = json.loads((folder / 'paired-control-receipt.json').read_text())
                receipts.append(receipt)
                self.assertEqual(state.max_steps, 2)
                self.assertFalse(callback_control.should_training_stop)
                event = [x for x in map(json.loads, (folder / 'events.jsonl').read_text().splitlines()) if x['event'] == 'train_begin'][0]
                self.assertEqual(event['max_steps'], 2)
            self.assertEqual(receipts[0]['initial_adapter_tensor_sha256'], receipts[1]['initial_adapter_tensor_sha256'])


if __name__ == '__main__':
    unittest.main()
