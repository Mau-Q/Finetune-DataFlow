"""Reuse the school's MinerU image/model for one offline advanced parsing check."""
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request
import zipfile

from pypdf import PdfReader, PdfWriter

# The numeric server UID may have no passwd entry inside the reused image.
os.environ.setdefault('USER', 'huruiqian')
os.environ.setdefault('LOGNAME', 'huruiqian')
import torch
from mineru.version import __version__

out = Path('/outputs')
out.mkdir(parents=True, exist_ok=True)
source = PdfReader('/inputs/source.pdf')
one = PdfWriter()
one.add_page(source.pages[0])
with (out / 'input-onepage.pdf').open('wb') as stream:
    one.write(stream)
identity = {'mineru': __version__, 'torch': torch.__version__, 'gpu': torch.cuda.get_device_name(0),
            'tier': 'advanced', 'synthetic_training_data': False, 'parse_pages': 1,
            'model_reused': '/models/MinerU2.5-Pro-2605-1.2B'}
(out / 'identity.json').write_text(json.dumps(identity, indent=2))
command = ['python3', '-m', 'mineru.kit.vlm_server.vllm_server',
           '--model', '/models/MinerU2.5-Pro-2605-1.2B', '--dtype', 'bfloat16',
           '--served-model-name', 'MinerU2.5-Pro-2605-1.2B', '--host', '127.0.0.1', '--port', '30000',
           '--gpu-memory-utilization', '0.25', '--max-model-len', '8192', '--max-num-seqs', '1',
           '--enforce-eager']
started = time.time()
with (out / 'vlm-server.log').open('w') as log:
    server = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
    try:
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            if server.poll() is not None:
                raise RuntimeError('MinerU VLM server exited; inspect vlm-server.log')
            try:
                with urllib.request.urlopen('http://127.0.0.1:30000/health', timeout=2) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(2)
        else:
            raise TimeoutError('MinerU VLM startup timed out')
        print('ADVANCED_VLM_READY', flush=True)
        with (out / 'parse.log').open('w') as parse_log:
            subprocess.run(['mineru-kit', 'parse', str(out / 'input-onepage.pdf'), '--tier', 'advanced',
                            '--format', 'zip', '-o', str(out / 'parsed.zip')],
                           stdout=parse_log, stderr=subprocess.STDOUT, timeout=900, check=True)
        with zipfile.ZipFile(out / 'parsed.zip') as archive:
            document = json.loads(archive.read('structured_content.json'))
        assert document.get('pages'), 'Missing parsed pages'
        identity.update(status='PASSED_ADVANCED_ONE_PAGE_PARSE',
                        parsed_pages=len(document['pages']), seconds=time.time() - started,
                        full_document=document.get('is_full_document'))
        (out / 'result.json').write_text(json.dumps(identity, indent=2))
        print(json.dumps(identity), flush=True)
    finally:
        server.terminate()
        try:
            server.wait(timeout=20)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()
