"""Host-only parser bridge; platform receives files, never Docker privileges."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

import json
import os
from pathlib import Path
import secrets
import subprocess
import threading
import uuid

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


MAX_BYTES = 100*1024*1024


def choose_gpu():
    output = subprocess.check_output(['nvidia-smi', '--query-gpu=uuid,memory.free', '--format=csv,noheader,nounits'], universal_newlines=True)
    cards = [(int(free.strip()), uid.strip()) for uid, free in (line.split(',') for line in output.splitlines())]
    free, uid = max(cards)
    if free < 16000:
        raise RuntimeError('没有至少 16 GB 空闲显存，暂缓解析')
    return uid


def parse_pdf(root, prior, script, content):
    job = root/'jobs'/uuid.uuid4().hex
    job.mkdir(parents=True)
    source = job/'source.pdf'
    source.write_bytes(content)
    output = job/'output'
    output.mkdir()
    gpu = choose_gpu()
    name = 'rui-mineru-job-'+job.name
    command = ['docker', 'run', '--rm', '--pull=never', '--name', name, '--network', 'none',
               '--gpus', 'device='+gpu, '--shm-size', '4g', '--memory', '32g', '--cpus', '8',
               '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--read-only',
               '--user', str(os.getuid())+':'+str(os.getgid()),
               '--tmpfs', '/tmp:rw,exec,size=4g,mode=1777', '--tmpfs', '/cache:rw,exec,size=3g,mode=1777',
               '--tmpfs', '/models/.locks:rw,size=64m,mode=1777',
               '-v', str(prior/'models')+':/models:ro', '-v', str(prior/'deploy/config.yaml')+':/deploy/config.yaml:ro',
               '-v', str(script)+':/deploy/job.py:ro', '-v', str(source)+':/inputs/source.pdf:ro',
               '-v', str(output)+':/outputs:rw']
    env = {'HOME': '/tmp', 'USER': 'huruiqian', 'LOGNAME': 'huruiqian', 'MINERU_HOME': '/tmp/mineru',
           'MINERU_CONFIG': '/deploy/config.yaml', 'MINERU_MODEL_SOURCE': 'local',
           'MINERU_MODEL_SMALL_BACKEND': 'torch', 'MINERU_MODEL_VLM_ENGINE': 'vllm',
           'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1', 'VLLM_NO_USAGE_STATS': '1',
           'DO_NOT_TRACK': '1', 'VLLM_HOST_IP': '127.0.0.1', 'GLOO_SOCKET_IFNAME': 'lo',
           'XDG_CACHE_HOME': '/cache', 'HF_HOME': '/cache/huggingface',
           'TRITON_CACHE_DIR': '/cache/triton', 'TORCHINDUCTOR_CACHE_DIR': '/cache/torchinductor'}
    for key, value in env.items():
        command += ['-e', key+'='+value]
    command += ['mineru-easyread:4.0.12-pro2605-bf16', '/deploy/job.py']
    try:
        with (job/'container.log').open('w') as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=2500, check=True)
    except Exception:
        subprocess.run(['docker', 'stop', '--time', '10', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        raise
    archive = (output/'parsed.zip').read_bytes()
    (job/'receipt.json').write_text(json.dumps({'sha256': hashlib.sha256(content).hexdigest(), 'gpu': gpu,
                                              'archive_sha256': hashlib.sha256(archive).hexdigest(), 'tier': 'advanced'}))
    return archive


def serve(root, prior, script, token, host='172.17.0.1', port=18082, parser=parse_pdf):
    lock = threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def reply(self, code, content, mime='application/json'):
            self.send_response(code)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        def authorized(self):
            return secrets.compare_digest(self.headers.get('Authorization', ''), 'Bearer '+token)
        def do_GET(self):
            if not self.authorized():
                return self.reply(403, b'{}')
            self.reply(200 if self.path == '/health' else 404, b'{"ready":true,"tier":"advanced"}')
        def do_POST(self):
            if not self.authorized():
                return self.reply(403, b'{}')
            if self.path != '/parse':
                return self.reply(404, b'{}')
            try:
                size = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                return self.reply(400, b'{}')
            if not 0 < size <= MAX_BYTES:
                return self.reply(413, b'{}')
            if not lock.acquire(blocking=False):
                return self.reply(429, b'{"error":"parser busy"}')
            try:
                self.connection.settimeout(60)
                content = self.rfile.read(size)
                if len(content) != size or not content[:1024].lstrip().startswith(b'%PDF-'):
                    return self.reply(400, b'{}')
                result = parser(root, prior, script, content)
                self.reply(200, result, 'application/zip')
            except Exception:
                self.reply(503, b'{"error":"MinerU parse failed; inspect host job logs"}')
            finally:
                lock.release()
    return ThreadingHTTPServer((host, port), Handler)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--prior', type=Path, required=True)
    p.add_argument('--script', type=Path, required=True)
    p.add_argument('--token-file', type=Path, required=True)
    a = p.parse_args()
    serve(a.root, a.prior, a.script, a.token_file.read_text().strip()).serve_forever()
