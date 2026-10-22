#!/bin/sh
set -eu
WORKSPACE=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export DATAFLOW_PYTHON="$WORKSPACE/.venvs/dataflow/bin/python"
export DATAFLOW_HOST="${DATAFLOW_HOST:-127.0.0.1}"
case "$DATAFLOW_HOST" in
  127.0.0.1|localhost|::1) ;;
  *) echo 'Development mode requires loopback. Use start-lan.sh for LAN sharing.' >&2; exit 2 ;;
esac
export DATAFLOW_PORT="${DATAFLOW_PORT:-8001}"
export DATAFLOW_APP=app.team_gateway:app
export DATAFLOW_READY_PATH=/team/status
export DATAFLOW_DEV_AUTO_LOGIN="${DATAFLOW_DEV_AUTO_LOGIN:-1}"
export DATAFLOW_COOKIE_SECURE=0
export PYTHONUTF8=1
export HF_HOME="$WORKSPACE/models/huggingface-cache"
export NO_PROXY="localhost,127.0.0.1,::1${NO_PROXY:+,$NO_PROXY}"
export no_proxy="$NO_PROXY"
exec "$WORKSPACE/repos/dataflow-webui/scripts/start.sh" "$@"
