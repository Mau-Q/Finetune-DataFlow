"""One complete PDF, offline advanced MinerU in the existing isolated image."""
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request
import zipfile

os.environ.setdefault('USER', 'huruiqian')
os.environ.setdefault('LOGNAME', 'huruiqian')
out = Path('/outputs')
args = ['python3', '-m', 'mineru.kit.vlm_server.vllm_server', '--model',
        '/models/MinerU2.5-Pro-2605-1.2B', '--dtype', 'bfloat16', '--served-model-name',
        'MinerU2.5-Pro-2605-1.2B', '--host', '127.0.0.1', '--port', '30000',
        '--gpu-memory-utilization', '0.25', '--max-model-len', '8192',
        '--max-num-seqs', '1', '--enforce-eager']
with (out/'vlm-server.log').open('w') as log:
    server = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT)
    try:
        deadline = time.monotonic()+600
        while time.monotonic() < deadline:
            if server.poll() is not None:
                raise RuntimeError('MinerU model server exited')
            try:
                with urllib.request.urlopen('http://127.0.0.1:30000/health', timeout=2) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(2)
        else:
            raise TimeoutError('MinerU startup timed out')
        with (out/'parse.log').open('w') as parse_log:
            subprocess.run(['mineru-kit', 'parse', '/inputs/source.pdf', '--tier', 'advanced',
                            '--format', 'zip', '-o', str(out/'parsed.zip')],
                           stdout=parse_log, stderr=subprocess.STDOUT, timeout=1800, check=True)
        with zipfile.ZipFile(out/'parsed.zip') as archive:
            document = json.loads(archive.read('structured_content.json'))
        assert document.get('is_full_document') is True and document.get('pages')
    finally:
        server.terminate()
        try:
            server.wait(timeout=20)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()
