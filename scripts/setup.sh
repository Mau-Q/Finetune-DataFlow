#!/usr/bin/env bash
# Install into this checkout only. Does not configure model services or datasets.
set -euo pipefail
if [[ "${1:-}" == "--help" ]]; then
    echo "Usage: ./scripts/setup.sh (requires git, uv, Node.js 22 and npm)"
    echo "Creates .venvs/dataflow with Python 3.12, installs local packages and builds WebUI."
    exit 0
fi
if [[ $# -ne 0 ]]; then
    echo "Unknown argument. Use --help." >&2
    exit 2
fi
root=$(cd -- "$(dirname -- "$0")/.." && pwd)
for tool in git uv node npm; do
    command -v "$tool" >/dev/null || { echo "Missing prerequisite: $tool" >&2; exit 1; }
done
cd "$root"
# Core, WebUI and DataFlex are ordinary source directories in this repository.
# Validate before creating an environment or installing dependencies.
for entry in repos/dataflow/dataflow/__init__.py repos/dataflow-webui/backend/app/services/training_bundles.py repos/dataflex/src/dataflex/cli.py; do
    [[ -f "$entry" ]] || { echo "Missing repository source: $entry. Fetch a complete checkout." >&2; exit 1; }
done
python="$root/.venvs/dataflow/bin/python"
if [[ ! -x "$python" ]]; then
    uv venv --python 3.12 --seed "$root/.venvs/dataflow"
fi
"$python" scripts/check-workspace.py
export CC="${CC:-/usr/bin/clang}"
export CXX="${CXX:-/usr/bin/clang++}"
uv pip install --python "$python" \
    -e "$root/repos/dataflow" \
    -e "$root/extensions/paper-dataflow" \
    -r "$root/repos/dataflow-webui/backend/requirements.txt" \
    -r "$root/locks/dataflow-test.txt"
cd "$root/repos/dataflow-webui/frontend"
npm ci --no-audit --no-fund
npm run build
echo "Ready. Start with: ./scripts/webui.sh --daemon (from the workspace root)"
