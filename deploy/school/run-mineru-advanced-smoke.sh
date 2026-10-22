#!/bin/bash
# Run on node01, after verifying hostname/account and current GPU occupancy.
set -euo pipefail
root="$HOME/DataFlow"
prior="$HOME/MinerU-EasyRead"
name=rui-mineru-advanced-smoke-20261022
gpu=GPU-ff8b5640-bfd0-97ff-2bfc-7486717f66a0
docker run -d --name "$name" --network none --gpus "device=$gpu" \
  --shm-size 4g --memory 32g --cpus 8 --cap-drop ALL \
  --security-opt no-new-privileges --read-only --user "$(id -u):$(id -g)" \
  --tmpfs /tmp:rw,exec,size=4g,mode=1777 \
  --tmpfs /cache:rw,exec,size=3g,mode=1777 \
  --tmpfs /models/.locks:rw,size=64m,mode=1777 \
  -v "$prior/models:/models:ro" \
  -v "$prior/deploy/config.yaml:/deploy/config.yaml:ro" \
  -v "$root/environments/mineru/mineru_advanced_smoke.py:/deploy/mineru_advanced_smoke.py:ro" \
  -v "$prior/inputs/505764842897/source.pdf:/inputs/source.pdf:ro" \
  -v "$root/runs/mineru/20261022-advanced-smoke:/outputs:rw" \
  -e HOME=/tmp -e USER=huruiqian -e LOGNAME=huruiqian \
  -e MINERU_HOME=/tmp/mineru -e MINERU_CONFIG=/deploy/config.yaml \
  -e MINERU_MODEL_SOURCE=local -e MINERU_MODEL_SMALL_BACKEND=torch \
  -e MINERU_MODEL_VLM_ENGINE=vllm -e HF_HUB_OFFLINE=1 \
  -e TRANSFORMERS_OFFLINE=1 -e VLLM_NO_USAGE_STATS=1 -e DO_NOT_TRACK=1 \
  -e VLLM_HOST_IP=127.0.0.1 -e GLOO_SOCKET_IFNAME=lo \
  -e XDG_CACHE_HOME=/cache -e HF_HOME=/cache/huggingface \
  -e TRITON_CACHE_DIR=/cache/triton -e TORCHINDUCTOR_CACHE_DIR=/cache/torchinductor \
  mineru-easyread:4.0.12-pro2605-bf16 /deploy/mineru_advanced_smoke.py
