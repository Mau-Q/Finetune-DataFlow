"""Start the WebUI with the Windows-compatible local environment."""

from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "repos" / "dataflow-webui" / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)


def main() -> None:
    from app.main import app
    import uvicorn

    host = os.environ.get("DATAFLOW_HOST", "127.0.0.1")
    port = int(os.environ.get("DATAFLOW_PORT", "8000"))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
