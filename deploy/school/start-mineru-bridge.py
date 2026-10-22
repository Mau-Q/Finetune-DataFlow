"""Idempotent manual start on node01; supports its existing Python 3.6."""
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def start(root):
    app = root/'app'
    work = root/'environments/platform'
    state = work/'mineru-bridge'
    state.mkdir(parents=True, exist_ok=True)
    token = (work/'mineru-bridge.token').read_text().strip()
    request = Request('http://172.17.0.1:18082/health', headers={'Authorization':'Bearer '+token})
    def ready():
        try:
            with urlopen(request, timeout=2) as response:
                return response.status == 200 and json.loads(response.read()).get('ready') is True
        except HTTPError:
            raise RuntimeError('Bridge port occupied by a service with different credentials')
        except URLError:
            return False
    if ready():
        print('MinerU bridge ready (existing process)')
        return
    command = [sys.executable, str(app/'deploy/school/mineru_bridge.py'),
               '--root', str(state), '--prior', str(root.parent/'MinerU-EasyRead'),
               '--script', str(app/'deploy/school/mineru_job.py'),
               '--token-file', str(work/'mineru-bridge.token')]
    with (state/'server.log').open('ab') as log:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log,
                                   stderr=log, start_new_session=True)
    (state/'pid').write_text(str(process.pid))
    for _ in range(120):
        if process.poll() is not None:
            raise RuntimeError('Bridge exited; inspect '+str(state/'server.log'))
        if ready():
            print('MinerU bridge ready, pid='+str(process.pid))
            return
        time.sleep(.25)
    raise RuntimeError('Bridge readiness timeout; inspect '+str(state/'server.log'))


if __name__ == '__main__':
    start(Path.home()/'DataFlow')
