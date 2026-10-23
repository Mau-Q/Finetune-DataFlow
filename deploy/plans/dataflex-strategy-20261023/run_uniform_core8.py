"""Finite sequential continuation: six reruns and seven frozen evaluations.

Host Python 3.6 compatible. Refuses reused attempts for this new cohort.
"""
import argparse
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path
from run_core8_suite import execute,free_check,record,require_mechanism,require_evaluation,HOST_RUN,GPU

ROOT=HOST_RUN/'uniform-core8-20261023'
RUN='/runs/strategy-20261023/uniform-core8-20261023'


def resource_gate(training):
    # The original 21,000 MiB guard covered microbatch2. These fresh reruns use
    # the separately measured microbatch1 profile; keep >=3 GiB over reserved.
    if training:
        measured=[json.loads(p.read_text())['peak_reserved_gib'] for p in ROOT.glob('G0[0-3]/attempt1/resource.json')]
        assert len(measured)==4
        minimum=max(16000,int(math.ceil(max(measured)*1024))+3072)
    else:
        measured=[json.loads((ROOT/name/'attempt1/resource.json').read_text())['peak_reserved_gib'] for name in ['G06','G07']]
        # Evaluation itself was already measured below 8 GiB reserved.
        minimum=12000
    free=int(subprocess.check_output(['nvidia-smi','--id='+GPU,'--query-gpu=memory.free','--format=csv,noheader,nounits']).decode().strip())
    record({'event':'uniform_resource_check','gpu2_free_mib':free,'minimum_free_mib':minimum,
            'phase':'microbatch1_training' if training else 'frozen_evaluation','reserved_profile_gib':measured,
            'basis':'Stage-specific observed allocation; no backend/configuration or tolerance change'})
    if free<minimum:raise RuntimeError('Stage resource guard: free MiB '+str(free)+' < '+str(minimum))


def completed(name):
    audit=require_mechanism(name,ROOT)
    folder=ROOT/name/'attempt1'
    resource=json.loads((folder/'resource.json').read_text())
    assert resource['status']=='TRAIN_VERIFIED' and resource['optimizer_steps']==24
    assert hashlib.sha256((folder/'output/adapter_model.safetensors').read_bytes()).hexdigest()==resource['adapter_sha256']
    assert all(hashlib.sha256((folder/f).read_bytes()).hexdigest()==digest for f,digest in audit['observation_sha256'].items())


def main(resume=False):
    plan=json.loads((ROOT/'cohort-plan.json').read_text())
    assert plan['new_optimizer_updates']==144 and plan['new_predictions']==448
    for i in range(6):
        name='G%02d'%i
        if (ROOT/name/'attempt1').exists() and not resume:
            raise RuntimeError('Existing attempt: inspect receipts; do not silently rerun '+name)
    for i in range(6):
        name='G%02d'%i
        if (ROOT/name/'successful-attempt.json').exists():
            completed(name);record({'event':'uniform_resume_verified_completed_training','name':name});continue
        if (ROOT/name/'attempt1').exists():raise RuntimeError('Incomplete attempt must be preserved: '+name)
        resource_gate(True)
        execute('uniform-core8-'+name,'diagnose_pair_runtime.py',
                [RUN+'/'+name+'/train.yaml',RUN+'/'+name+'/attempt1','--hash-base','--trace-dropout'])
        execute('uniform-core8-'+name+'-audit','audit_uniform_core8.py',[name,'--root',RUN],False)
        require_mechanism(name,ROOT)
    for name in ['BASE']+['G%02d'%i for i in range(6)]:
        if (ROOT/'evaluation'/name/'metrics.json').exists():
            require_evaluation(name,64,ROOT);record({'event':'uniform_resume_verified_completed_evaluation','name':name});continue
        resource_gate(False)
        execute('uniform-core8-'+name+'-evaluation','evaluate_uniform_core8.py',[name,'--root',RUN])
        require_evaluation(name,64,ROOT)
    execute('uniform-core8-final-summary','summarize_uniform_core8.py',['--root',RUN],False)
    record({'event':'uniform_core8_all_training_evaluation_and_summary_completed'})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--resume',action='store_true')
    args=parser.parse_args()
    try:main(args.resume)
    except Exception as error:
        record({'event':'uniform_core8_stopped','error':repr(error)})
        raise
