#!/bin/sh
set -eu
WORKSPACE=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export MINERU_HOME="$WORKSPACE/models/mineru"
export HF_HOME="$WORKSPACE/models/huggingface-cache"
export MINERU_MODEL_SMALL_BACKEND=torch
export MINERU_MODEL_VLM_ENGINE=llama-cpp
export MINERU_MODEL_SOURCE=local
exec "$WORKSPACE/.venvs/mineru/bin/mineru-kit" "$@"
