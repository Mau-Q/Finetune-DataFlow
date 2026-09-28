#!/bin/sh
set -eu
WORKSPACE=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export DATAFLOW_PYTHON="$WORKSPACE/.venvs/dataflow/bin/python"
export DATAFLOW_HOST=127.0.0.1
export DATAFLOW_PORT=8000
export HF_HOME="$WORKSPACE/models/huggingface-cache"
export NO_PROXY="localhost,127.0.0.1,::1${NO_PROXY:+,$NO_PROXY}"
export no_proxy="$NO_PROXY"
exec "$WORKSPACE/repos/dataflow-webui/scripts/start.sh" "$@"
