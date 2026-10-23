"""Save/reload evaluation of the isolated resolved pair, with explicit determinism."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import torch
import evaluate_frozen as evaluator
from observed_run import prepare_reproducibility

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('name',choices=['G06','G07']);parser.add_argument('--root',type=Path,required=True)
    args=parser.parse_args()
    prepare_reproducibility({'seed':42}, 'torch-math-cublas4096-v2')
    evaluator.ROOT=args.root
    evaluator.main(args.name)
    path=args.root/'evaluation'/args.name/'metrics.json'
    receipt=json.loads(path.read_text())
    receipt['execution_protocol']={'deterministic_execution':'torch-math-cublas4096-v2','full_determinism':False,'deterministic_algorithms':torch.are_deterministic_algorithms_enabled(),
        'cublas_workspace_config':os.environ.get('CUBLAS_WORKSPACE_CONFIG'),
        'wrapper_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'scope':'Resolved pair reload/generation; old non-deterministic evaluation remains historical'}
    path.write_text(json.dumps(receipt,indent=2)+'\n')
