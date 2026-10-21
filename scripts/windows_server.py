"""Start the WebUI with the Windows-compatible local environment.

The upstream DataFlow package exposes Langkit operators lazily. Langkit pulls
whylogs-sketching, which currently has no usable CPython 3.12 Windows wheel and
would require a native compiler. If Langkit is absent, remove only those two
optional operators before the WebUI scans the registry.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "repos" / "dataflow-webui" / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)


def disable_unavailable_langkit() -> None:
    """Keep the WebUI usable when the optional Langkit package is absent."""
    if importlib.util.find_spec("langkit") is not None:
        return

    module = importlib.import_module("dataflow.operators.general_text")
    structure = getattr(module, "_import_structure", None)
    if not isinstance(structure, dict):
        return

    removed = []
    for name in ("LangkitFilter", "LangkitSampleEvaluator"):
        if structure.pop(name, None) is not None:
            removed.append(name)
    if removed:
        module.__all__ = [name for name in module.__all__ if name not in removed]
        print(
            "Langkit operators disabled on this machine because the optional "
            "langkit dependency is not installed: " + ", ".join(removed),
            file=sys.stderr,
        )


def main() -> None:
    disable_unavailable_langkit()

    from app.main import app
    import uvicorn

    host = os.environ.get("DATAFLOW_HOST", "127.0.0.1")
    port = int(os.environ.get("DATAFLOW_PORT", "8000"))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
