"""Frozen BASE/core8 generation under the already verified numerical protocol."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import torch
import evaluate_frozen as evaluator
import observed_run as observer


def main(name, root):
    observer.prepare_reproducibility({'seed':42}, 'torch-math-cublas4096-v2')
    evaluator.ROOT=root
    evaluator.main(name)
    path=root/'evaluation'/name/'metrics.json'
    receipt=json.loads(path.read_text())
    backends={n:getattr(torch.backends.cuda,n+'_sdp_enabled')() for n in ['flash','math','mem_efficient','cudnn']}
    assert backends=={'flash':False,'math':True,'mem_efficient':False,'cudnn':False}
    assert torch.are_deterministic_algorithms_enabled() and torch.backends.cudnn.deterministic
    receipt['execution_protocol']={'deterministic_execution':'torch-math-cublas4096-v2','full_determinism':False,
        'deterministic_algorithms':torch.are_deterministic_algorithms_enabled(),'sdp_backends':backends,
        'cudnn_deterministic':torch.backends.cudnn.deterministic,'cudnn_benchmark':torch.backends.cudnn.benchmark,
        'cublas_workspace_config':os.environ.get('CUBLAS_WORKSPACE_CONFIG'),
        'cuda_launch_blocking':os.environ.get('CUDA_LAUNCH_BLOCKING'),
        'observer_sha256':hashlib.sha256(Path(observer.__file__).read_bytes()).hexdigest(),
        'wrapper_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    path.write_text(json.dumps(receipt,indent=2)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('name',choices=['BASE']+['G%02d'%i for i in range(8)])
    parser.add_argument('--root',type=Path,required=True)
    args=parser.parse_args();main(args.name,args.root)
