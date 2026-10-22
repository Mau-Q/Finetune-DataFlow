#!/bin/bash
# Execute in the dedicated node01 container. /wheelhouse must be a verified local bundle.
set -euo pipefail
export PIP_NO_INDEX=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
export HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1
# This container is dedicated to training. The reused image includes an older
# vLLM serving stack; remove its incompatible, unused extras inside this
# container only. None belongs to the resolved training dependency closure.
python -m pip uninstall -y vllm mistral-common sentence-transformers gguf boto3 botocore \
  s3transfer runai-model-streamer-s3 googleapis-common-protos \
  opentelemetry-exporter-otlp opentelemetry-exporter-otlp-proto-common \
  opentelemetry-exporter-otlp-proto-grpc opentelemetry-exporter-otlp-proto-http \
  opentelemetry-proto opentelemetry-sdk opentelemetry-semantic-conventions
python -m pip install --no-index --find-links /wheelhouse -r /work/offline-resolved.txt
# The release wheel labelled ABI FALSE failed the actual Torch 2.6 import check.
# Build the unmodified source offline against the installed Torch/CUDA instead.
mkdir -p /work/built-wheels
if ! compgen -G '/work/built-wheels/causal_conv1d-1.6.0-*.whl' >/dev/null; then
  CAUSAL_CONV1D_FORCE_BUILD=TRUE MAX_JOBS=4 python -m pip wheel \
    --no-build-isolation --no-deps --no-index /work/causal_conv1d-1.6.0.tar.gz \
    -w /work/built-wheels
fi
python -m pip uninstall -y causal-conv1d
python -m pip install --no-index --find-links /wheelhouse /work/built-wheels/causal_conv1d-1.6.0-*.whl
python -m pip check
python - <<'PY'
import importlib.metadata as metadata
import json
from pathlib import Path
import torch
import triton
import bitsandbytes
import causal_conv1d
from fla.modules import FusedRMSNormGated
from fla.ops.gated_delta_rule import chunk_gated_delta_rule, fused_recurrent_gated_delta_rule
from dataflex.cli import main
from llamafactory.data.template import TEMPLATES

assert 'qwen3_5_nothink' in TEMPLATES
assert torch.cuda.is_available() and torch.cuda.device_count() == 1
assert torch.__version__.split('+')[0] == '2.6.0' and torch.version.cuda == '12.4'
assert torch._C._GLIBCXX_USE_CXX11_ABI is False
names = ['torch','torchvision','torchaudio','triton','transformers','peft','accelerate',
         'datasets','trl','bitsandbytes','flash-linear-attention','fla-core','causal-conv1d',
         'dataflex','llamafactory']
record = {'versions': {name: metadata.version(name) for name in names},
          'python_executable': __import__('sys').executable,
          'gpu': torch.cuda.get_device_name(0), 'cuda': torch.version.cuda,
          'cxx11_abi': torch._C._GLIBCXX_USE_CXX11_ABI,
          'entrypoint_imports': 'passed', 'training': 'NOT_RUN'}
Path('/work/environment.json').write_text(json.dumps(record, indent=2))
print(json.dumps(record, indent=2))
PY
python -m pip freeze > /work/installed-requirements.txt
