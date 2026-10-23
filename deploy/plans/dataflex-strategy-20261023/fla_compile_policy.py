"""Process-local deterministic FLA configuration choice, with compile checks.

The Triton 3.2 autotuner otherwise benchmarks candidates independently in every
new process. For FLA kernels only, rank candidates by their declared order and
compile them without launching benchmark kernels. Unsupported configurations
retain infinite rank. Actual kernel launches and math remain the original FLA
implementation. This is an explicit experimental execution policy.
"""
import hashlib
from pathlib import Path

AUTOTUNER_SHA256 = '0497baf6ff4c48c4b3764bd84940ebbd7ac015e2d9d71e80fbb6949a9cf62ded'
POLICY = 'fla-compile-ordered-config-v3'


def install():
    import triton.runtime.autotuner as runtime
    from triton.compiler.errors import CompileTimeAssertionFailure
    from triton.runtime.errors import OutOfResources
    actual = hashlib.sha256(Path(runtime.__file__).read_bytes()).hexdigest()
    if actual != AUTOTUNER_SHA256:
        raise ValueError('Triton autotuner changed; this compile-only policy needs revalidation')
    original = runtime.Autotuner._bench
    calls = []

    def ordered(self, *args, config, **meta):
        if not self.base_fn.__module__.startswith('fla.'):
            return original(self, *args, config=config, **meta)
        if meta.keys() & config.kwargs.keys():
            raise ValueError('Conflicting FLA launch metadata')
        rank = next(i for i, candidate in enumerate(self.configs) if candidate is config)
        current = dict(meta, **config.all_kwargs())
        current['warmup'] = True  # Triton JIT compiles; it does not launch a kernel.
        supported = True
        error = None
        try:
            self.fn.run(*args, **current)
        except (OutOfResources, CompileTimeAssertionFailure) as exception:
            supported = False
            error = type(exception).__name__
        calls.append({'kernel': self.base_fn.__module__+'.'+self.base_fn.__name__,
                      'kwargs': config.kwargs, 'num_warps': config.num_warps,
                      'num_stages': config.num_stages, 'rank': rank,
                      'compile_supported': supported, 'error': error})
        return [float(rank) if supported else float('inf')]*3

    runtime.Autotuner._bench = ordered
    return {'policy': POLICY, 'triton_autotuner_sha256': actual,
            'selection': 'First compile-supported candidate in FLA declaration order; no elapsed-time ranking',
            'scope': 'FLA only; task process only; no installed-file or disk-cache edits'}, calls
