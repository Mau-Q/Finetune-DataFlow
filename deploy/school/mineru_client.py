#!/usr/bin/env python3
"""MinerU-compatible CLI that submits only PDF bytes to the host parser bridge."""
import argparse
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler


def parse(source, output, token_file=Path('/work/mineru-bridge.token'), base='http://172.17.0.1:18082'):
    content = Path(source).read_bytes()
    token = token_file.read_text().strip()
    opener = build_opener(ProxyHandler({}))
    deadline = time.monotonic()+2400
    while True:
        request = Request(base+'/parse', data=content, headers={'Authorization': 'Bearer '+token, 'Content-Type': 'application/pdf'})
        try:
            with opener.open(request, timeout=2400) as response:
                archive = response.read()
            break
        except HTTPError as exc:
            if exc.code != 429 or time.monotonic() >= deadline:
                raise RuntimeError('MinerU bridge failed: HTTP '+str(exc.code)) from None
            time.sleep(3)
    target = Path(output)
    temp = target.with_suffix('.tmp')
    temp.write_bytes(archive)
    temp.replace(target)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=['parse'])
    p.add_argument('source')
    p.add_argument('-o', required=True)
    p.add_argument('--format', choices=['zip'], default='zip')
    p.add_argument('--tier', choices=['advanced'], default='advanced')
    args = p.parse_args()
    parse(args.source, args.o)
