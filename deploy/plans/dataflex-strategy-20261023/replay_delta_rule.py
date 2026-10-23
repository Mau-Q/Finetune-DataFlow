"""Replay a captured delta-rule input packet, without loading the 9B model."""
import argparse
import inspect
import importlib
import json
import sys
from pathlib import Path

import torch
from safetensors.torch import load_file, save_file
import transformers.models.qwen3_5.modeling_qwen3_5 as qwen
import observed_run as observer
from probe_preselection import describe, digest


def main(source, output, disable_autocast, disable_bf16_reduction, pin_chunk_o=None):
    output.mkdir(exist_ok=False)
    observer.prepare_reproducibility({}, 'torch-math-cublas4096-v2')
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cuda.matmul.allow_bf16_reduced_precision_reduction = not disable_bf16_reduction
    receipt = json.loads((source/'delta-call.json').read_text())
    cpu = load_file(str(source/'delta-inputs.safetensors'))
    scalars = {k: v for k, v in receipt['inputs'].items() if k not in cpu}
    scalars.update(scalars.pop('kwargs', {}))
    inputs = {}
    for k, v in cpu.items():
        layout = receipt.get('layouts', {}).get(k)
        if layout is None:
            inputs[k] = v.to('cuda')
        else:
            stride, offset = layout['stride'], layout['storage_offset']
            size = offset + sum((n-1)*s for n, s in zip(v.shape, stride)) + 1
            storage = torch.empty(size, dtype=v.dtype, device='cuda')
            inputs[k] = storage.as_strided(v.shape, stride, offset)
            inputs[k].copy_(v)
    native = getattr(importlib.import_module(receipt['native_module']), receipt['native_name'])
    pinned = None
    if pin_chunk_o is not None:
        kernel = importlib.import_module('fla.ops.common.chunk_o').chunk_fwd_kernel_o
        while not hasattr(kernel, 'configs'):
            kernel = kernel.fn
        options = [c for c in kernel.configs if c.kwargs == {'BK': pin_chunk_o, 'BV': pin_chunk_o}]
        assert len(options) == 1
        kernel.configs = options
        kernel.cache.clear()
        kernel.cache_results = False
        pinned = str(options[0])
    stages = importlib.import_module('fla.ops.gated_delta_rule.chunk')
    stage_repeat = {'index': 0}
    import functools
    for name in ['l2norm_fwd', 'chunk_local_cumsum', 'chunk_scaled_dot_kkt_fwd',
                 'solve_tril', 'recompute_w_u_fwd', 'chunk_gated_delta_rule_fwd_h', 'chunk_fwd_o']:
        original = getattr(stages, name)

        def wrap(function, name):
            @functools.wraps(function)
            def call(*args, **kwargs):
                before = describe({'args': args, 'kwargs': kwargs})
                value = function(*args, **kwargs)
                observer.emit(output/'stages.jsonl', {
                    'repeat': stage_repeat['index'], 'stage': name,
                    'inputs': before, 'output': describe(value)})
                return value
            return call

        setattr(stages, name, wrap(original, name))
    autocast = receipt['autocast_cuda'] and not disable_autocast
    records = []
    for i in range(4):
        stage_repeat['index'] = i
        with torch.no_grad(), torch.autocast('cuda', dtype=torch.bfloat16, enabled=autocast):
            value, state = native(**inputs, **scalars)
        records.append({'repeat': i, 'output': digest(value), 'state': describe(state)})
        save_file({'output': value.detach().cpu().contiguous()}, str(output/('output-%d.safetensors'%i)))
    configs = {}
    for module_name, module in list(sys.modules.items()):
        if not module_name.startswith('fla.') or module is None:
            continue
        for name, kernel in vars(module).items():
            seen = set()
            while hasattr(kernel, 'fn') and id(kernel) not in seen and getattr(kernel, 'best_config', None) is None:
                seen.add(id(kernel))
                kernel = kernel.fn
            config = getattr(kernel, 'best_config', None)
            if config is not None and hasattr(config, 'num_warps'):
                configs[module_name+'.'+name] = {
                    'kwargs': config.kwargs, 'num_warps': config.num_warps,
                    'num_stages': config.num_stages,
                    'cache': {str(k): str(v) for k, v in getattr(kernel, 'cache', {}).items()}}
    result = {'status': 'ISOLATED_DELTA_RULE_REPLAY', 'source': str(source),
              'input_packet_sha256': observer.sha(source/'delta-inputs.safetensors'),
              'original_output': digest(load_file(str(source/'delta-output.safetensors'))['output']) if (source/'delta-output.safetensors').exists() else None,
              'autocast': autocast,
              'bf16_reduced_precision_reduction': torch.backends.cuda.matmul.allow_bf16_reduced_precision_reduction,
              'matmul_tf32': torch.backends.cuda.matmul.allow_tf32,
              'pinned_chunk_o_config': pinned,
              'native_source_sha256': __import__('hashlib').sha256(inspect.getsource(native).encode()).hexdigest(),
              'script_sha256': observer.sha(Path(__file__)), 'repeats': records,
              'autotune_configs': configs}
    (output/'receipt.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--disable-autocast', action='store_true')
    parser.add_argument('--disable-bf16-reduction', action='store_true')
    parser.add_argument('--pin-chunk-o', type=int, choices=[32, 64, 128])
    args = parser.parse_args()
    main(args.source, args.output, args.disable_autocast, args.disable_bf16_reduction, args.pin_chunk_o)
