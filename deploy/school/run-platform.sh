#!/bin/bash
# The image is a local snapshot of the dedicated offline-installed container.
set -euo pipefail
root="$HOME/DataFlow"
mkdir -p "$root/app/repos/dataflow-webui/backend/data"
docker run -d --pull=never --name rui-dataflow-platform-20261022 \
  --network bridge -p 127.0.0.1:18001:8001 --shm-size 2g --memory 16g --cpus 4 \
  -v "$root/app:/app:ro" -v "$root/environments/platform:/work" \
  -v "$root/offline/wheels/py312-torch26-cu124:/wheelhouse:ro" \
  -v rui-dataflow-platform-state-20261022:/state \
  -v rui-dataflow-platform-legacy-data-20261022:/app/repos/dataflow-webui/backend/data \
  -e HF_HUB_OFFLINE=1 -e HF_DATASETS_OFFLINE=1 -e HF_HUB_DISABLE_TELEMETRY=1 \
  -e DO_NOT_TRACK=1 -e PIP_NO_INDEX=1 -e PIP_DISABLE_PIP_VERSION_CHECK=1 \
  -e DATAFLOW_TEAM_DIR=/state/team -e DATAFLOW_WORKSPACE_DIR=/state/workspace \
  -e DATAFLOW_COOKIE_SECURE=0 -e TIKTOKEN_CACHE_DIR=/work/tokenizers \
  -e OMP_NUM_THREADS=4 -e MKL_NUM_THREADS=4 -e PYTHONUNBUFFERED=1 \
  -e PYTHONPATH=/app/repos/dataflow-webui/backend \
  -w /app/repos/dataflow-webui/backend --entrypoint python \
  rui/dataflow-platform:20261022 -m uvicorn app.team_gateway:app \
  --host 0.0.0.0 --port 8001 --no-access-log
