"""Formal training, bounded repeatability and generation share one actual policy."""
import argparse
import json
from pathlib import Path

import observed_run as observer
from extended_execution_policy import PROTOCOL, persist


def main(mode, root, name, attempt):
    observer.ROOT = root
    folder = root/name/attempt
    if mode in ['train', 'probe']:
        config = root/name/'train.yaml'
        if mode == 'probe':
            import probe_preselection
            probe_preselection.main(config, folder, None, stop_step=4)
        else:
            import diagnose_pair_runtime as diagnostic
            diagnostic.original_install = observer.install
            observer.install = lambda cls, out: diagnostic.enable_diagnostics(cls, out, True, True)
            observer.train(config, folder)
    elif mode == 'evaluate':
        import evaluate_frozen as evaluator
        import torch
        observer.prepare_reproducibility({'seed': 42}, PROTOCOL)
        evaluator.ROOT = root
        try:
            evaluator.main(name)
        finally:
            if (root/'evaluation'/name).exists():
                persist(root/'evaluation'/name)
        path = root/'evaluation'/name/'metrics.json'
        receipt = json.loads(path.read_text())
        receipt['execution_protocol'] = {
            'deterministic_execution': PROTOCOL, 'full_determinism': False,
            'deterministic_algorithms': torch.are_deterministic_algorithms_enabled(),
            'sdp_backends': {n: getattr(torch.backends.cuda, n+'_sdp_enabled')()
                             for n in ['flash', 'math', 'mem_efficient', 'cudnn']},
            'wrapper_sha256': observer.sha(Path(__file__)),
            'observer_sha256': observer.sha(Path(observer.__file__)),
            'fla_policy_sha256': observer.sha(path.parent/'fla-policy.json')}
        path.write_text(json.dumps(receipt, indent=2)+'\n')
    else:
        import audit_observations as audit
        audit.ROOT = root
        audit.main(name)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['train', 'probe', 'evaluate', 'audit'])
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--attempt', default='attempt1')
    args = parser.parse_args()
    main(args.mode, args.root, args.name, args.attempt)
