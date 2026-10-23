"""Task-scoped FLA launch policy; never edits the installed package or its caches."""
import hashlib
import importlib
from pathlib import Path

CHUNK_O_SHA256 = '07adcb9de033832b432494a9db14897dedfb522214a11cc62657d8c2eaa65bcd'
POLICY = 'fla-chunk-o-bk64-bv64-w4-s3-v1'


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
