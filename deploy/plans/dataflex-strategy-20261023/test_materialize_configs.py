import importlib.util
from pathlib import Path
import tempfile
import unittest

import yaml

spec = importlib.util.spec_from_file_location('materialize', Path(__file__).with_name('materialize_configs.py'))
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)


class MaterializationTests(unittest.TestCase):
    def test_school_paths_and_family_specific_budgets(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/'configs'
            report = module.materialize(out)
            self.assertEqual(len(report['runs']), 8)
            for row in report['runs']:
                self.assertFalse(row['ready_for_training'])
                cfg = yaml.safe_load(Path(row['path']).read_text())
                self.assertEqual(cfg['model_name_or_path'], '/models/Qwen3.5-9B')
                self.assertTrue(cfg['output_dir'].startswith('/runs/strategy-20261023/'))
                self.assertEqual(cfg['max_steps'], 24)
                self.assertEqual(cfg['per_device_train_batch_size']*cfg['gradient_accumulation_steps'], 4)
                if row['run_id'] in ['G06', 'G07']:
                    self.assertFalse(cfg['full_determinism'])
                if cfg['train_type'] in ['dynamic_mix','dynamic_select']:
                    self.assertEqual(cfg['train_step'], 24)
                if row['run_id']=='G05':
                    component = yaml.safe_load(Path(row['path']).with_name('components.yaml').read_text())
                    self.assertEqual(component['mixers']['odm']['params']['warmup_steps'], 0)
                    self.assertEqual(cfg['mixture_sample_rule'], 'mixture')
            with self.assertRaises(FileExistsError): module.materialize(out)

    def test_invalid_runtime_root_has_no_filesystem_side_effects(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/'configs'
            with self.assertRaises(ValueError): module.materialize(out, '/runs/../old-run')
            self.assertFalse(out.exists())


if __name__=='__main__': unittest.main()
