"""Actual CLI control: unchanged warmup, fixed FLA chunk-o launch configuration."""
import argparse
import json
from pathlib import Path

import observed_run as observer
from fla_numerical_policy import pin_chunk_o
import probe_preselection as probe


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--steps', type=int, default=4, choices=[1, 4])
    args = parser.parse_args()
    observer.prepare_reproducibility({}, 'torch-math-cublas4096-v2')
    policy = pin_chunk_o()
    policy['wrapper_sha256'] = observer.sha(Path(__file__))
    policy['policy_script_sha256'] = observer.sha(Path(__file__).with_name('fla_numerical_policy.py'))
    # The parent already exists; the probe itself must remain absent until the
    # existing observer creates it, so keep this receipt beside the attempt.
    (args.folder.parent/'fla-policy.json').write_text(json.dumps(policy, indent=2)+'\n')
    probe.main(args.config, args.folder, None, stop_step=args.steps)
