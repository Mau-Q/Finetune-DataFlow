from fastapi import FastAPI
from app.core.config import settings
from app.core.logger_setup import logger
from app.core.dataflow_setup import setup_dataflow_core
from app.core.container import container
from app.api.v1.handlers import install_exception_handlers
from app.api.v1.router import api_router as api_v1

from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.responses import Response
from pathlib import Path

app = FastAPI()

DIST_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
INDEX_FILE = DIST_DIR / "index.html"


def create_app() -> FastAPI:
    from app.services.dataset_backups import DatasetBackups
    import os
    backups = DatasetBackups(Path(settings.BASE_DIR) / settings.RESOURCE_DIR,
                             os.environ.get('DATAFLOW_DATASET_BACKUP_DIR'))
    backups.recover_if_needed()
    setup_dataflow_core()
    container.init()
    app = FastAPI(title="DataFlow Backend", version="1.0.0")
    worker_token = os.environ.get('DATAFLOW_WORKER_TOKEN')
    if os.environ.get('DATAFLOW_TEAM_WORKER') and not worker_token:
        raise RuntimeError('Private project worker requires DATAFLOW_WORKER_TOKEN')
    if worker_token:
        from app.services.worker_auth import install_worker_auth
        install_worker_auth(app, worker_token)
    @app.middleware('http')
    async def personal_identity(request, call_next):
        from app.services.personal_execution import identity
        # Only the authenticated loopback gateway may supply a team identity.
        actor = request.headers.get('x-team-user') if worker_token else None
        token = identity.set(actor)
        try:
            return await call_next(request)
        finally:
            identity.reset(token)

    app.state.dataset_backups = backups
    app.router.add_event_handler('startup', backups.start)
    app.router.add_event_handler('shutdown', backups.stop)
    app.include_router(api_v1, prefix="/api/v1")
    app.add_middleware(
        CORSMiddleware,
        # allow_origins=settings.CORS_ORIGINS,
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    DIST_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
    INDEX_FILE = DIST_DIR / "index.html"
    install_exception_handlers(app)

    if not INDEX_FILE.exists():
        logger.warning("Warning: UI index file not found, please build the frontend first")
    else:
        app.mount("/", StaticFiles(directory=DIST_DIR, html=True), name="ui")

    return app

app = create_app()

@app.get("/ui/{full_path:path}")
def spa_fallback(full_path: str):
    target = DIST_DIR / full_path
    if target.exists() and target.is_file():
        # 例如 /ui/assets/xxx.js 这种静态文件会被直接命中
        return FileResponse(target)
    return FileResponse(INDEX_FILE)

# --- 3. Startup event to refresh operator cache ---
@app.on_event("startup")
def startup_refresh_ops_cache():
    try:
        for lang in ("zh", "en"):
            container.operator_registry.refresh()
            container.operator_registry.dump_ops_to_json(lang=lang)
        logger.info("Operator cache regenerated at startup.")
    except Exception as e:
        logger.error(f"Failed to regenerate operator cache at startup: {e}")