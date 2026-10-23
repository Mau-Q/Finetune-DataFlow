"""Trace the first real Qwen delta-rule call and preserve its full input packet."""
import argparse
import functools
import hashlib
import inspect
import json
from pathlib import Path

import torch
from safetensors.torch import save_file
from torch.utils._python_dispatch import TorchDispatchMode
import transformers.models.qwen3_5.modeling_qwen3_5 as qwen
import probe_preselection as probe
import observed_run as observer


def main(config, folder):
    native = qwen.torch_chunk_gated_delta_rule
    used = False

    class Trace(TorchDispatchMode):
        def __init__(self):
            super().__init__()
            self.index = 0

        def __torch_dispatch__(self, func, types, args=(), kwargs=None):
            kwargs = kwargs or {}
            inputs = probe.describe({'args': args, 'kwargs': kwargs})
            output = func(*args, **kwargs)
            observer.emit(folder/'delta-ops.jsonl', {
                'index': self.index, 'operation': str(func),
                'inputs': inputs, 'output': probe.describe(output)})
            self.index += 1
            return output

    @functools.wraps(native)
    def wrapped(*args, **kwargs):
        nonlocal used
        if used:
            return native(*args, **kwargs)
        used = True
        bound = inspect.signature(native).bind(*args, **kwargs)
        bound.apply_defaults()
        values = dict(bound.arguments)
        save_file({k: v.detach().cpu().contiguous() for k, v in values.items() if torch.is_tensor(v)},
                  str(folder/'delta-inputs.safetensors'))
        (folder/'delta-call.json').write_text(json.dumps({
            'inputs': probe.describe(values),
            'autocast_cuda': torch.is_autocast_enabled('cuda'),
            'autocast_dtype': str(torch.get_autocast_dtype('cuda')),
            'grad_enabled': torch.is_grad_enabled(),
            'native_source_sha256': hashlib.sha256(inspect.getsource(native).encode()).hexdigest(),
            'wrapper_sha256': observer.sha(Path(__file__)),
        }, indent=2))
        with Trace():
            output = native(*args, **kwargs)
        save_file({'output': output[0].detach().cpu().contiguous()}, str(folder/'delta-output.safetensors'))
        return output

    qwen.torch_chunk_gated_delta_rule = wrapped
    probe.main(config, folder, 1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('folder', type=Path)
    args = parser.parse_args()
    main(args.config, args.folder)
