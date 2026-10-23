"""CPU-only strict validation of the new isolated, deterministic G06/G07 pair."""
import argparse
import hashlib
import json
from pathlib import Path
import torch
from safetensors.torch import load_file
import audit_observations as audit


def read(path):return json.loads(path.read_text())
def rows(path):return [json.loads(line) for line in path.read_text().splitlines()]


def verify(root):
    folders={name:root/name/'attempt1' for name in ['G06','G07']}
    identities={name:read(folder/'paired-control-receipt.json') for name,folder in folders.items()}
    for identity in identities.values():
        assert not identity['full_determinism_requested'] and identity['deterministic_execution_requested']=='torch-math-cublas4096-v2' and identity['deterministic_algorithms'] and identity['cudnn_deterministic']
        assert identity['cublas_workspace_config']==':4096:8' and identity['cuda_launch_blocking'] is None
        assert identity['sdp_backends']=={'flash':False,'math':True,'mem_efficient':False,'cudnn':False}
    assert identities['G06']['initial_adapter_tensor_sha256']==identities['G07']['initial_adapter_tensor_sha256']
    initial={name:read(folder/'initial-model-hashes.json') for name,folder in folders.items()}
    assert initial['G06']==initial['G07'] and len(initial['G06'])>=3046
    exact=[]
    for micro in range(1,9):
        for part in ['A','B']:
            tensors=[load_file(str(folders[name]/('gradient-%02d-%s.safetensors'%(micro,part))))['gradient'] for name in ['G06','G07']]
            assert torch.equal(*tensors),(micro,part,'Warmup tensors differ')
            exact.append({'micro':micro,'part':part,'bitwise_equal':True})
    gradients={name:rows(folder/'optimizer-gradients.jsonl') for name,folder in folders.items()}
    expected_trainable=next(row['trainable_tensors'] for row in rows(folders['G06']/'events.jsonl') if row['event']=='train_begin')
    counts=[]
    for step,(a,b) in enumerate(zip(gradients['G06'],gradients['G07']),start=1):
        assert a['step']==b['step']==step and a['all_finite'] and b['all_finite']
        assert set(a['tensors'])==set(b['tensors'])
        assert len(a['tensors'])==expected_trainable
        if step<=4:
            assert all(a['tensors'][key]['sha256']==b['tensors'][key]['sha256'] for key in a['tensors']),('Optimizer-input gradient tensors differ at warmup step',step)
            counts.append(len(a['tensors']))
        else:
            assert any(a['tensors'][key]['sha256']!=b['tensors'][key]['sha256'] for key in a['tensors'])
    assert len(gradients['G06'])==len(gradients['G07'])==5 and len(counts)==4
    first_losses={name:rows(folder/'weights.jsonl')[0]['losses'] for name,folder in folders.items()}
    assert first_losses['G06']==first_losses['G07'],'Different sample losses before first weighted backward'
    audit.ROOT=root
    audit.main('G06')
    audit.main('G07')  # Original strict test, without the same-forward workaround.
    paired=read(folders['G07']/'audit.json')['paired_control']
    assert paired['trajectory_status']=='MATCHED_WITHIN_PREDECLARED_TOLERANCE'
    receipt={'status':'PAIR_GRADIENT_MISMATCH_RESOLVED','scope':'Isolated rerun; historical attempts and evaluations unchanged',
             'optimizer_updates':48,'per_run_updates':24,'same_initial_model_tensor_hashes':len(initial['G06']),
             'warmup_representative_tensor_comparisons':exact,'warmup_optimizer_input_parameter_counts':counts,
             'warmup_optimizer_input_parameter_hashes_equal':True,
             'first_weighted_optimizer_inputs_differ':True,'strict_original_gradient_audit_passed':True,
             'first_weighted_sample_losses_equal':True,'first_weighted_sample_losses':first_losses['G06'],
             'warmup_max_gradient_norm_relative_difference':paired['warmup_max_gradient_norm_relative_difference'],
             'first_weighted_gradient_norms':paired['first_weighted_gradient_norms'],
             'original_tolerance':{'atol':1e-4,'rtol':.02},'protocols':identities,
             'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (root/'resolution-verdict.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True)
    verify(parser.parse_args().root)
