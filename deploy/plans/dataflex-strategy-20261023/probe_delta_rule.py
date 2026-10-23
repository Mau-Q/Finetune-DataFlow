"""Trace the first real Qwen delta-rule call and preserve its full input packet."""
import argparse
import functools
import hashlib
import inspect
import importlib
import json
from pathlib import Path

import torch
from safetensors.torch import save_file
import transformers.models.qwen3_5.modeling_qwen3_5 as qwen
import probe_preselection as probe
import observed_run as observer


def main(config, folder):
    native = qwen.chunk_gated_delta_rule or qwen.torch_chunk_gated_delta_rule
    used = False
    active = False
    if native.__module__.startswith('fla.'):
        stages = importlib.import_module('fla.ops.gated_delta_rule.chunk')
        for name in ['l2norm_fwd', 'chunk_local_cumsum', 'chunk_scaled_dot_kkt_fwd',
                     'solve_tril', 'recompute_w_u_fwd', 'chunk_gated_delta_rule_fwd_h', 'chunk_fwd_o']:
            original = getattr(stages, name)

            def wrap(function, name):
                @functools.wraps(function)
                def call(*args, **kwargs):
                    before = probe.describe({'args': args, 'kwargs': kwargs}) if active else None
                    value = function(*args, **kwargs)
                    if active:
                        observer.emit(folder/'delta-stages.jsonl', {
                            'stage': name, 'inputs': before, 'output': probe.describe(value)})
                    return value
                return call

            setattr(stages, name, wrap(original, name))

    @functools.wraps(native)
    def wrapped(*args, **kwargs):
        nonlocal used, active
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
            'layouts': {k: {'stride': list(v.stride()), 'storage_offset': v.storage_offset(),
                             'pointer_mod_256': v.data_ptr() % 256}
                        for k, v in values.items() if torch.is_tensor(v)},
            'native_module': native.__module__,
            'native_name': native.__name__,
            'autocast_cuda': torch.is_autocast_enabled('cuda'),
            'autocast_dtype': str(torch.get_autocast_dtype('cuda')),
            'grad_enabled': torch.is_grad_enabled(),
            'native_source_sha256': hashlib.sha256(inspect.getsource(native).encode()).hexdigest(),
            'wrapper_sha256': observer.sha(Path(__file__)),
        }, indent=2))
        active = True
        try:
            output = native(*args, **kwargs)
        finally:
            active = False
        save_file({'output': output[0].detach().cpu().contiguous()}, str(folder/'delta-output.safetensors'))
        return output

    if qwen.chunk_gated_delta_rule is not None:
        qwen.chunk_gated_delta_rule = wrapped
    else:
        qwen.torch_chunk_gated_delta_rule = wrapped
    conv = qwen.causal_conv1d_fn
    if conv is not None:
        conv_used = False

        @functools.wraps(conv)
        def trace_conv(*args, **kwargs):
            nonlocal conv_used
            first = not conv_used
            conv_used = True
            before = probe.describe({'args': args, 'kwargs': kwargs}) if first else None
            value = conv(*args, **kwargs)
            if first:
                observer.emit(folder/'delta-conv.jsonl', {
                    'inputs': before, 'output': probe.describe(value),
                    'native_module': conv.__module__})
            return value

        qwen.causal_conv1d_fn = trace_conv
    probe.main(config, folder, 1)
    if not used:
        raise RuntimeError('Target delta-rule entry point was not reached')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('folder', type=Path)
    args = parser.parse_args()
    main(args.config, args.folder)
