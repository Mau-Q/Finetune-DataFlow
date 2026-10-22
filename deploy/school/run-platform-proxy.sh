#!/bin/bash
# The Linux Caddy binary is downloaded on Mac and verified after upload.
set -euo pipefail
root="$HOME/DataFlow/environments/platform-proxy"
mkdir -p "$root/state"
chmod 700 "$root/state"
docker run -d --pull=never --name rui-dataflow-https-20261022 \
  --network host --restart unless-stopped --read-only --cap-drop ALL \
  --security-opt no-new-privileges --user "$(id -u):$(id -g)" \
  --memory 256m --cpus 1 --tmpfs /tmp:rw,size=64m,mode=1777 \
  -v "$root:/work:ro" -v "$root/state:/state:rw" \
  -e HOME=/tmp -e XDG_DATA_HOME=/state/data -e XDG_CONFIG_HOME=/state/config \
  --entrypoint /work/bin/caddy rui/dataflow-platform:20261022 \
  run --config /work/Caddyfile --adapter caddyfile
