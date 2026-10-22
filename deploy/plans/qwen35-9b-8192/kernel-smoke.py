"""Exercise the CUDA extensions used by Qwen3.5 before loading the full weights."""
import json
import faulthandler
import os
from pathlib import Path
import time

os.environ.setdefault('TORCHINDUCTOR_COMPILE_THREADS', '1')
import torch
import torch.nn.functional as functional
from causal_conv1d import causal_conv1d_fn
from fla.ops.gated_delta_rule import chunk_gated_delta_rule

faulthandler.dump_traceback_later(180, repeat=True)
torch.manual_seed(42)
started = time.time()
device = 'cuda'
dtype = torch.bfloat16
x = torch.randn(1, 32, 128, device=device, dtype=dtype, requires_grad=True)
weight = torch.randn(32, 4, device=device, dtype=dtype, requires_grad=True)
actual = causal_conv1d_fn(x, weight, activation='silu')
expected = functional.silu(functional.conv1d(x, weight.unsqueeze(1), padding=3, groups=32)[..., :128])
torch.testing.assert_close(actual, expected, atol=0.05, rtol=0.05)
actual.float().square().mean().backward()
assert torch.isfinite(x.grad).all() and torch.isfinite(weight.grad).all()
q, k, v = [torch.randn(1, 128, 2, 128, device=device, dtype=dtype, requires_grad=True)
           for _ in range(3)]
g = functional.logsigmoid(torch.randn(1, 128, 2, device=device, dtype=torch.float32))
beta = torch.sigmoid(torch.randn(1, 128, 2, device=device, dtype=dtype))
output, _ = chunk_gated_delta_rule(q=q, k=k, v=v, g=g, beta=beta,
                                  use_qk_l2norm_in_kernel=True, output_final_state=False)
output.float().square().mean().backward()
assert torch.isfinite(output).all()
assert all(item.grad is not None and torch.isfinite(item.grad).all() for item in [q, k, v])
record = {'status': 'PASSED_CUDA_KERNEL_FORWARD_BACKWARD',
          'causal_conv1d_reference_close': True, 'chunk_gated_delta_gradients_finite': True,
          'seconds': time.time() - started, 'gpu': torch.cuda.get_device_name(0),
          'full_model_training': False}
Path('/runs/kernel-smoke.json').write_text(json.dumps(record, indent=2))
print(json.dumps(record), flush=True)
faulthandler.cancel_dump_traceback_later()
