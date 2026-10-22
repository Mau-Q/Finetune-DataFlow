"""Shared local-development entry point; no shell or OS-specific paths."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / 'repos/dataflow-webui/backend'


def main():
    parser = argparse.ArgumentParser(description='Start a loopback-only DataFlow workspace')
    parser.add_argument('--require-login', action='store_true', help='Use normal accounts instead of development auto-login')
    args = parser.parse_args()
    host = os.environ.get('DATAFLOW_HOST', '127.0.0.1')
    if host not in {'127.0.0.1', '::1', 'localhost'}:
        parser.error('Local development must bind to loopback; use the LAN deployment guide for sharing')
    os.environ['DATAFLOW_DEV_AUTO_LOGIN'] = '0' if args.require_login else '1'
    os.environ['DATAFLOW_COOKIE_SECURE'] = '0'
    os.environ.setdefault('DATAFLOW_TEAM_DIR', str(BACKEND / 'data/collaboration'))
    os.environ.setdefault('HF_HOME', str(ROOT / 'models/huggingface-cache'))
    sys.path.insert(0, str(BACKEND))
    os.chdir(BACKEND)
    import uvicorn
    print('DataFlow local development: ' + ('normal login' if args.require_login else 'automatic local identity'), flush=True)
    uvicorn.run('app.team_gateway:app', host=host, port=int(os.environ.get('DATAFLOW_PORT', '8001')),
                proxy_headers=False, access_log=False)


if __name__ == '__main__':
    main()
