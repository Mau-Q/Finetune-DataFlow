"""CPU contracts only; fixture success never stands for real GPU acceptance."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml

sys.path.insert(0,str(Path(__file__).parent))
import prepare_uniform_core8 as preparation
from summarize_uniform_core8 import validate_protocol,collect


class UniformCohortContracts(unittest.TestCase):
    def fixture(self, directory):
        source=Path(directory)/'source';source.mkdir()
        (source/'data').mkdir();(source/'data-manifest.json').write_text('{}')
        snapshot=source/'paired-initialization-v2/adapter_init.safetensors'
        snapshot.parent.mkdir();snapshot.write_bytes(b'CPU fixture only')
        resolved=source/'gradient-resolution-v2-20261023';resolved.mkdir()
        verdict={'status':'PAIR_GRADIENT_MISMATCH_RESOLVED','protocols':{'G06':{
            'snapshot_sha256':preparation.sha(snapshot),'initial_adapter_tensor_sha256':'fixture'}}}
        (resolved/'resolution-verdict.json').write_text(json.dumps(verdict))
        (resolved/'resolution-summary.json').write_text('{}')
        (resolved/'evaluation').mkdir()
        for name in ['G06','G07']:
            (resolved/name).mkdir();(resolved/'evaluation'/name).mkdir()
        for i in range(6):
            name='G%02d'%i;folder=source/name/'attempt1';folder.mkdir(parents=True)
            (source/name/'successful-attempt.json').write_text(json.dumps({'observation_dir':str(folder)}))
            components={'selectors':{'random':{'params':{'cache_dir':str(folder/'strategy-cache')}}}}
            component=source/name/'components.yaml';component.write_text(yaml.safe_dump(components))
            cfg={'max_steps':24,'per_device_train_batch_size':1,'gradient_accumulation_steps':4,
                 'train_type':'dynamic_select' if i in [1,2,3] else 'static','component_name':'random',
                 'components_cfg_file':str(component),'output_dir':str(folder/'output')}
            (folder/'actual-config.yaml').write_text(yaml.safe_dump(cfg))
            (folder/'manifest.json').write_text(json.dumps({'components_sha256':preparation.sha(component)}))
            cache=folder/'strategy-cache';cache.mkdir();(cache/'sentinel').write_text('preserve')
        return source

    def test_preparation_keeps_old_cache_and_uses_namespace_safe_relative_links(self):
        with tempfile.TemporaryDirectory() as temp:
            source=self.fixture(temp);root=Path(temp)/'cohort'
            with patch.object(preparation,'DATA_SHA',preparation.sha(source/'data-manifest.json')):
                preparation.prepare(root,source)
            for link in [root/'data',root/'data-manifest.json',root/'G06',root/'evaluation/G07']:
                self.assertTrue(link.exists());self.assertTrue(link.is_symlink())
                self.assertFalse(Path(link.readlink()).is_absolute())
            cfg=yaml.safe_load((root/'G01/train.yaml').read_text())
            components=yaml.safe_load((root/'G01/components.yaml').read_text())
            self.assertFalse(cfg['full_determinism'])
            self.assertEqual(components['selectors']['random']['params']['cache_dir'],str(root/'G01/attempt1/strategy-cache'))
            self.assertFalse((root/'G01/attempt1').exists())
            self.assertEqual((source/'G01/attempt1/strategy-cache/sentinel').read_text(),'preserve')
            with self.assertRaises(FileExistsError):preparation.prepare(root,source)

    def test_changed_component_identity_is_rejected_before_output_is_created(self):
        with tempfile.TemporaryDirectory() as temp:
            source=self.fixture(temp);root=Path(temp)/'cohort'
            (source/'G02/components.yaml').write_text('tampered: true')
            with patch.object(preparation,'DATA_SHA',preparation.sha(source/'data-manifest.json')):
                with self.assertRaises(AssertionError):preparation.prepare(root,source)
            self.assertFalse(root.exists())

    def test_protocol_receipt_rejects_partial_or_overwritten_backend_policy(self):
        receipt={'deterministic_execution_requested':preparation.PROTOCOL,'deterministic_algorithms':True,
                 'cudnn_deterministic':True,'cudnn_benchmark':False,'full_determinism_requested':False,
                 'cublas_workspace_config':':4096:8','cuda_launch_blocking':None,
                 'sdp_backends':{'flash':False,'math':True,'mem_efficient':False,'cudnn':False}}
        validate_protocol(receipt)
        for key,value in [('cublas_workspace_config',':16:8'),('full_determinism_requested',True),
                          ('sdp_backends',dict(receipt['sdp_backends'],mem_efficient=True))]:
            changed=copy.deepcopy(receipt);changed[key]=value
            with self.assertRaises(AssertionError):validate_protocol(changed)

    def test_reused_pair_receipt_cannot_change_after_plan_is_frozen(self):
        with tempfile.TemporaryDirectory() as temp:
            source=self.fixture(temp);root=Path(temp)/'cohort';digest=preparation.sha(source/'data-manifest.json')
            with patch.object(preparation,'DATA_SHA',digest):preparation.prepare(root,source)
            (source/'gradient-resolution-v2-20261023/resolution-verdict.json').write_text('{}')
            with patch('summarize_uniform_core8.DATA_SHA',digest):
                with self.assertRaises(AssertionError):collect(root)


if __name__=='__main__':unittest.main()
