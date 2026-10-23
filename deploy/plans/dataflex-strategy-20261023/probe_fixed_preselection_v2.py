"""Bounded warmup with fixed delta output and fused gated-norm launches."""
import argparse
import functools
import json
from pathlib import Path

import observed_run as observer
from fla_numerical_policy import pin_fla_attention
import probe_preselection as probe


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('folder', type=Path)
    args = parser.parse_args()
    observer.prepare_reproducibility({}, 'torch-math-cublas4096-v2')
    policy = pin_fla_attention()
    policy['wrapper_sha256'] = observer.sha(Path(__file__))
    policy['policy_script_sha256'] = observer.sha(Path(__file__).with_name('fla_numerical_policy.py'))
    (args.folder.parent/'fla-policy.json').write_text(json.dumps(policy, indent=2)+'\n')
    from fla.modules.fused_norm_gate import FusedRMSNormGated
    from safetensors.torch import save_file
    original = FusedRMSNormGated.forward
    captured = False

    @functools.wraps(original)
    def norm(self, x, g, *other, **kwargs):
        global captured
        first = not captured
        if first:
            captured = True
            save_file({k: v.detach().cpu().contiguous() for k, v in {'x': x, 'g': g, 'weight': self.weight}.items()},
                      str(args.folder/'norm-inputs.safetensors'))
            (args.folder/'norm-call.json').write_text(json.dumps({
                'eps': self.eps, 'activation': self.activation,
                'inputs': probe.describe({'x': x, 'g': g, 'weight': self.weight}),
            }, indent=2))
        value = original(self, x, g, *other, **kwargs)
        if first:
            save_file({'output': value.detach().cpu().contiguous()}, str(args.folder/'norm-output.safetensors'))
        return value

    FusedRMSNormGated.forward = norm
    probe.main(args.config, args.folder, None, stop_step=4)
