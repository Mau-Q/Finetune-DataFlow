"""The validated PyTorch + FLA policy, installed once before CUDA/model setup."""
import json
from pathlib import Path

PROTOCOL = 'torch-math-cublas4096-v2+fla-compile-ordered-config-v3'
_receipt = None
_calls = None


def install():
    global _receipt, _calls
    if _receipt is None:
        from fla_numerical_policy import pin_fla_attention
        from fla_compile_policy import install as install_ordered
        _receipt = pin_fla_attention()
        _receipt['deterministic_fla_selection'], _calls = install_ordered()
        _receipt['policy'] = 'fla-compile-ordered-config-v3'
        import hashlib
        _receipt['sources'] = {
            name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ['extended_execution_policy.py', 'fla_numerical_policy.py', 'fla_compile_policy.py']}
    return _receipt


def persist(folder):
    if _receipt is not None:
        (folder/'fla-policy.json').write_text(json.dumps(_receipt, indent=2)+'\n')
        (folder/'fla-compile-configs.json').write_text(json.dumps(_calls, indent=2)+'\n')
