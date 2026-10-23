"""Task-scoped FLA launch policy; never edits the installed package or its caches."""
import hashlib
import importlib
from pathlib import Path

CHUNK_O_SHA256 = '07adcb9de033832b432494a9db14897dedfb522214a11cc62657d8c2eaa65bcd'
POLICY = 'fla-chunk-o-bk64-bv64-w4-s3-v1'
NORM_SHA256 = 'e620731d73fd069944b37d5b4a76cf00adcaba2b6745f5600351751cec85afe1'


def pin_chunk_o(module=None):
    module = module or importlib.import_module('fla.ops.common.chunk_o')
    source_hash = hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
    if source_hash != CHUNK_O_SHA256:
        raise ValueError('FLA chunk_o source changed; revalidate this numerical policy')
    kernel = module.chunk_fwd_kernel_o
    seen = set()
    while not hasattr(kernel, 'configs'):
        if id(kernel) in seen or not hasattr(kernel, 'fn'):
            raise ValueError('Unsupported Triton autotuner chain')
        seen.add(id(kernel))
        kernel = kernel.fn
    candidates = [c for c in kernel.configs
                  if c.kwargs == {'BK': 64, 'BV': 64} and c.num_warps == 4 and c.num_stages == 3]
    if len(candidates) != 1:
        raise ValueError('Expected exactly one validated FLA launch configuration')
    kernel.configs = candidates
    kernel.cache.clear()
    kernel.cache_results = False
    return {'policy': POLICY, 'source_sha256': source_hash,
            'kernel': 'fla.ops.common.chunk_o.chunk_fwd_kernel_o',
            'kwargs': candidates[0].kwargs, 'num_warps': 4, 'num_stages': 3,
            'candidate_count': 1, 'disk_cache_results': False}


def pin_fla_attention():
    chunk = pin_chunk_o()
    module = importlib.import_module('fla.modules.fused_norm_gate')
    digest = hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
    if digest != NORM_SHA256:
        raise ValueError('FLA gated-norm source changed; revalidate this numerical policy')
    records = [chunk]
    for name in ['layer_norm_gated_fwd_kernel', 'layer_norm_gated_bwd_kernel']:
        kernel = getattr(module, name)
        while not hasattr(kernel, 'configs'):
            kernel = kernel.fn
        candidates = [c for c in kernel.configs
                      if c.kwargs == {'BT': 16} and c.num_warps == 4 and c.num_stages == 2]
        if len(candidates) != 1:
            raise ValueError('Expected one validated gated-norm configuration')
        kernel.configs = candidates
        kernel.cache.clear()
        kernel.cache_results = False
        records.append({'kernel': 'fla.modules.fused_norm_gate.'+name,
                        'source_sha256': digest, 'kwargs': {'BT': 16},
                        'num_warps': 4, 'num_stages': 2, 'candidate_count': 1})
    return {'policy': 'fla-linear-fixed-v2', 'kernels': records}
