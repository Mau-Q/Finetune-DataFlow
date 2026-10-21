#!/bin/sh
set -eu
root=$(CDPATH= cd -P "$(dirname "$0")/.." && pwd)
python="$root/.venvs/dataflow/bin/python"
backend="$root/repos/dataflow-webui/backend"
export DATAFLOW_TEAM_DIR="${DATAFLOW_TEAM_DIR:-$backend/data/collaboration}"
export DATAFLOW_COOKIE_SECURE="${DATAFLOW_COOKIE_SECURE:-1}"
cd "$backend"
case "${1:-start}" in
  init)
    shift
    PYTHONPATH="$backend${PYTHONPATH:+:$PYTHONPATH}" "$python" scripts/team_admin.py --legacy-root "$backend" "$@"
    ;;
  start)
    # This port is private. An HTTPS LAN proxy is the shared entry point.
    exec "$python" -m uvicorn app.team_gateway:app --host 127.0.0.1 --port "${DATAFLOW_PORT:-8001}" --proxy-headers --forwarded-allow-ips 127.0.0.1 --no-access-log
    ;;
  *) echo 'Usage: scripts/start-lan.sh [init --name ADMIN | start]' >&2; exit 2 ;;
esac
