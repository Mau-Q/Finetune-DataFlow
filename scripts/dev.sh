#!/bin/sh
set -eu
root=$(CDPATH= cd -P "$(dirname "$0")/.." && pwd)
python="${DATAFLOW_PYTHON:-$root/.venvs/dataflow/bin/python}"
if [ ! -x "$python" ]; then
    echo "Missing Python environment. Run ./scripts/setup.sh first." >&2
    exit 1
fi
export PYTHONUTF8=1
exec "$python" "$root/scripts/dev_server.py" "$@"
