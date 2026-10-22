"""Authenticated loopback workers, shared by Windows, macOS and LAN mode."""
import asyncio
from pathlib import Path
import os
import secrets
import socket
import subprocess
import sys
import time

import httpx
from app.services.data_library import LibraryError

BACKEND = Path(__file__).resolve().parents[2]
STARTUP_TIMEOUT = 180


class Workers:
    def __init__(self, state):
        self.state = Path(state)
        self.processes = {}
        self.endpoints = {}
        self.locks = {}

    async def client(self, project):
        project_id = project['id']
        async with self.locks.setdefault(project_id, asyncio.Lock()):
            process = self.processes.get(project_id)
            if process is None or process.poll() is not None:
                # Reserve an ephemeral address. The worker token prevents trusting
                # a different local process if it takes the port before startup.
                with socket.socket() as reservation:
                    reservation.bind(('127.0.0.1', 0))
                    port = reservation.getsockname()[1]
                token = secrets.token_urlsafe(32)
                endpoint = f'http://127.0.0.1:{port}'
                env = os.environ.copy()
                extension = BACKEND.parents[2] / 'extensions/paper-dataflow'
                env['PYTHONPATH'] = os.pathsep.join([str(BACKEND), str(extension), env.get('PYTHONPATH', '')])
                env.update(DATAFLOW_WORKSPACE_DIR=project['root'], DATAFLOW_TEAM_WORKER='1',
                           DATAFLOW_WORKER_TOKEN=token, DATAFLOW_PROJECT_ID=project_id,
                           DATAFLOW_DATASET_BACKUP_DIR=str(Path(project['root']) / 'backups/datasets'),
                           DATAFLOW_TRAINING_DIR=str(Path(project['root']) / 'data/model_training'),
                           PYTHONUTF8='1')
                self.state.mkdir(parents=True, exist_ok=True)
                with (self.state / (project_id + '.worker.log')).open('ab') as log:
                    process = subprocess.Popen(
                        [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1',
                         '--port', str(port), '--no-proxy-headers', '--no-access-log'],
                        cwd=BACKEND, env=env, stdout=log, stderr=log)
                self.processes[project_id] = process
                self.endpoints[project_id] = endpoint, token
                try:
                    async with httpx.AsyncClient(trust_env=False, timeout=1) as probe:
                        # Cold Windows installs can spend over a minute loading
                        # native CPU libraries. Keep a finite readiness deadline.
                        deadline = time.monotonic() + STARTUP_TIMEOUT
                        while time.monotonic() < deadline:
                            if process.poll() is not None:
                                raise LibraryError('项目服务启动失败，请检查工作进程日志', 503)
                            try:
                                response = await probe.get(endpoint + '/_worker/ready', headers={'X-Worker-Token': token})
                                if response.status_code == 200:
                                    break
                            except httpx.TransportError:
                                pass
                            await asyncio.sleep(.1)
                        else:
                            raise LibraryError('项目服务启动超时', 503)
                except BaseException:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            await asyncio.to_thread(process.wait, 10)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            await asyncio.to_thread(process.wait)
                    raise
            endpoint, token = self.endpoints[project_id]
        return httpx.AsyncClient(base_url=endpoint, headers={'X-Worker-Token': token},
                                 trust_env=False, timeout=STARTUP_TIMEOUT + 30)

    async def close(self):
        for process in self.processes.values():
            if process.poll() is None:
                process.terminate()
        for process in self.processes.values():
            try:
                await asyncio.to_thread(process.wait, 10)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait)
        self.processes.clear()
        self.endpoints.clear()
