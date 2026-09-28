#!/bin/sh
set -eu

root=$(CDPATH= cd -P "$(dirname "$0")/.." && pwd)
python="$root/.venvs/dataflow/bin/python"

if [ ! -x "$python" ]; then
    echo "Missing DataFlow Python: $python" >&2
    exit 1
fi
if ! "$python" -c 'import flask, pytest' 2>/dev/null; then
    echo "Missing local test dependencies. Run: uv pip install --python .venvs/dataflow/bin/python -r locks/dataflow-test.txt" >&2
    exit 1
fi

cd "$root"
"$python" -m pytest repos/dataflow/test/cpu_only -q -m 'not gpu'
PYTHONPATH="$root/repos/dataflow-webui/backend:$root/repos/dataflow${PYTHONPATH:+:$PYTHONPATH}" \
    "$python" -m pytest repos/dataflow-webui/backend/tests -q
"$python" -m pytest extensions/paper-dataflow/test -q
