"""Keep loopback project backends private even on Windows without Unix sockets."""
import secrets
from fastapi.responses import JSONResponse


def install_worker_auth(app, token):
    @app.middleware('http')
    async def authenticate(request, call_next):
        if not secrets.compare_digest(request.headers.get('x-worker-token', ''), token):
            return JSONResponse({'detail': 'Private worker'}, status_code=403)
        if request.url.path == '/_worker/ready':
            return JSONResponse({'ready': True})
        return await call_next(request)
