#!/bin/bash
# Execute only inside the dedicated, verified training container.
set -euo pipefail
export HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1
export TORCHINDUCTOR_COMPILE_THREADS=1
export PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"
test -f /models/Qwen3.5-9B/transfer-manifest.json
while test -f /work/GPU_SELECTION_PENDING; do sleep 2; done
python - <<'PY'
import torch
free, total = torch.cuda.mem_get_info()
if free < 28 * 2**30:
    raise RuntimeError(f'Insufficient currently free GPU memory: {free / 2**30:.2f} GiB; other jobs preserved')
print(f'GPU currently free: {free / 2**30:.2f} / {total / 2**30:.2f} GiB', flush=True)
PY
python /work/smoke.py prepare > /runs/logs/prepare.log 2>&1
python /work/smoke.py train --length 512 > /runs/logs/train-512.log 2>&1
python /work/smoke.py reload > /runs/logs/adapter-reload.log 2>&1
python /work/smoke.py train --length 4096 > /runs/logs/train-4096.log 2>&1
python /work/smoke.py train --length 8192 > /runs/logs/train-8192.log 2>&1
echo ALL_SYNTHETIC_TRAINING_AND_RELOAD_CHECKS_PASSED
