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
import time
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


class WarmParser:
    """One owned offline model per bridge, serial parsing, bounded idle GPU lease."""
    def __init__(self, root, prior, script, idle_seconds=300):
        self.root, self.prior, self.script = root, prior, script
        self.idle_seconds = idle_seconds
        self.owner = hashlib.sha256((str(root.resolve())+':'+str(os.getuid())).encode()).hexdigest()[:24]
        (root/'jobs').mkdir(parents=True, exist_ok=True)
        (root/'engines').mkdir(exist_ok=True)
        self.state = root/'worker.json'

    def running(self, name):
        result = subprocess.run(['docker','inspect',name], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True)
        if result.returncode:
            return False
        info = json.loads(result.stdout)[0]
        if info['Config'].get('Labels',{}).get('dataflow.mineru.owner') != self.owner:
            raise RuntimeError('Refusing to use a parser container with a different owner')
        return info['State']['Running']

    def ensure(self):
        fingerprint = hashlib.sha256(self.script.read_bytes()).hexdigest()
        if self.state.exists():
            state = json.loads(self.state.read_text())
            engine = Path(state['engine'])
            if engine.parent != self.root/'engines':
                raise RuntimeError('Invalid parser engine path')
            if state.get('script_sha256') == fingerprint and self.running(state['container']) and (engine/'ready.json').exists():
                (engine/'lease').touch()
                return state, True
            if self.running(state['container']):
                subprocess.run(['docker','stop','--time','30',state['container']], check=True, stdout=subprocess.DEVNULL)
        gpu = choose_gpu()
        name = 'rui-mineru-warm-'+uuid.uuid4().hex
        engine = self.root/'engines'/uuid.uuid4().hex
        engine.mkdir()
        command = ['docker', 'run', '-d', '--rm', '--pull=never', '--name', name, '--label', 'dataflow.mineru.owner='+self.owner, '--network', 'none',
                   '--gpus', 'device='+gpu, '--shm-size', '4g', '--memory', '32g', '--cpus', '8',
                   '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--read-only',
                   '--user', str(os.getuid())+':'+str(os.getgid()),
                   '--tmpfs', '/tmp:rw,exec,size=4g,mode=1777', '--tmpfs', '/cache:rw,exec,size=3g,mode=1777',
                   '--tmpfs', '/models/.locks:rw,size=64m,mode=1777',
                   '-v', str(self.prior/'models')+':/models:ro', '-v', str(self.prior/'deploy/config.yaml')+':/deploy/config.yaml:ro',
                   '-v', str(self.script)+':/deploy/job.py:ro', '-v', str(self.root/'jobs')+':/jobs:rw',
                   '-v', str(engine)+':/engine:rw']
        env = {'HOME': '/tmp', 'USER': 'huruiqian', 'LOGNAME': 'huruiqian', 'MINERU_HOME': '/tmp/mineru',
               'MINERU_CONFIG': '/deploy/config.yaml', 'MINERU_MODEL_SOURCE': 'local',
               'MINERU_MODEL_SMALL_BACKEND': 'torch', 'MINERU_MODEL_VLM_ENGINE': 'vllm',
               'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1', 'VLLM_NO_USAGE_STATS': '1',
               'DO_NOT_TRACK': '1', 'VLLM_HOST_IP': '127.0.0.1', 'GLOO_SOCKET_IFNAME': 'lo',
               'XDG_CACHE_HOME': '/cache', 'HF_HOME': '/cache/huggingface',
               'TRITON_CACHE_DIR': '/cache/triton', 'TORCHINDUCTOR_CACHE_DIR': '/cache/torchinductor'}
        for key, value in env.items():
            command += ['-e', key+'='+value]
        command += ['mineru-easyread:4.0.12-pro2605-bf16', '/deploy/job.py', '--serve', '--idle-seconds', str(self.idle_seconds)]
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
        state = {'container':name,'engine':str(engine),'gpu':gpu,'script_sha256':fingerprint}
        self.state.write_text(json.dumps(state))
        deadline = time.monotonic()+600
        while time.monotonic() < deadline:
            if not self.running(name):
                raise RuntimeError('MinerU model exited; inspect '+str(engine/'vlm-server.log'))
            if (engine/'ready.json').exists():
                (engine/'lease').touch()
                return state, False
            time.sleep(2)
        subprocess.run(['docker','stop','--time','30',name], stdout=subprocess.DEVNULL)
        raise TimeoutError('MinerU startup timed out')

    def __call__(self, root, prior, script, content):
        started = time.monotonic()
        job = self.root/'jobs'/uuid.uuid4().hex
        job.mkdir()
        (job/'source.pdf').write_bytes(content)
        state, reused = self.ensure()
        engine = Path(state['engine'])
        stop = threading.Event()
        def heartbeat():
            while not stop.wait(10):
                (engine/'lease').touch()
        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            inner = '/jobs/'+job.name
            with (job/'parse.log').open('w') as log:
                subprocess.run(['docker','exec',state['container'],'mineru-kit','parse',inner+'/source.pdf',
                                '--tier','advanced','--format','zip','-o',inner+'/parsed.zip'],
                               stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1800)
        except Exception:
            # docker-exec timeout alone can leave its child inside the container.
            # Stop only this bridge's verified worker to end that parse.
            if self.running(state['container']):
                subprocess.run(['docker','stop','--time','30',state['container']], stdout=subprocess.DEVNULL)
            raise
        finally:
            (engine/'lease').touch()
            stop.set();thread.join()
        archive = (job/'parsed.zip').read_bytes()
        (job/'receipt.json').write_text(json.dumps({'sha256':hashlib.sha256(content).hexdigest(),
            'archive_sha256':hashlib.sha256(archive).hexdigest(), 'tier':'advanced',
            'gpu':state['gpu'], 'container':state['container'], 'reused_model':reused,
            'seconds':round(time.monotonic()-started,3)}))
        return archive


def serve(root, prior, script, token, host='172.17.0.1', port=18082, parser=None):
    parser = parser or WarmParser(root, prior, script)
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
