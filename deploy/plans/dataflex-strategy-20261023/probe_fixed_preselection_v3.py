"""Four-step actual-CLI gate with complete FLA forward/backward choice control."""
import argparse
import json
from pathlib import Path

import observed_run as observer
from fla_numerical_policy import pin_fla_attention
from fla_compile_policy import install
import probe_preselection as probe


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('folder', type=Path)
    args = parser.parse_args()
    observer.prepare_reproducibility({}, 'torch-math-cublas4096-v2')
    policy = pin_fla_attention()
    policy['deterministic_fla_selection'], calls = install()
    policy['policy'] = 'fla-compile-ordered-config-v3'
    policy['wrapper_sha256'] = observer.sha(Path(__file__))
    policy['policy_script_sha256'] = observer.sha(Path(__file__).with_name('fla_numerical_policy.py'))
    policy['compile_policy_script_sha256'] = observer.sha(Path(__file__).with_name('fla_compile_policy.py'))
    (args.folder.parent/'fla-policy.json').write_text(json.dumps(policy, indent=2)+'\n')
    try:
        probe.main(args.config, args.folder, None, stop_step=4)
    finally:
        (args.folder.parent/'fla-compile-configs.json').write_text(json.dumps(calls, indent=2)+'\n')
