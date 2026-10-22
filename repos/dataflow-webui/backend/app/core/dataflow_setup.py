"""Initialize the DataFlow files the backend reads at runtime."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from app.core.config import settings
from loguru import logger


_REQUIRED_CORE_DIRS = ("api_pipelines", "example_data")


def dataflow_core_ready(core_dir: Path) -> bool:
    """Return whether a core directory has the minimum usable DataFlow layout."""
    return all((core_dir / name).is_dir() for name in _REQUIRED_CORE_DIRS)


def setup_dataflow_core() -> None:
    """Create a usable core directory with the same interpreter as the backend.

    open-dataflow 1.0.10 registers ``dataflow`` as ``dataflow.cli:app`` and
    deliberately has no ``dataflow.__main__``.  ``python -m dataflow init`` is
    consequently invalid.  Avoiding ``os.system`` and process-wide ``chdir``
    also prevents a failed initialization from being mistaken for success.
    """
    core_dir = Path(settings.DATAFLOW_CORE_DIR)
    core_dir.mkdir(parents=True, exist_ok=True)

    if dataflow_core_ready(core_dir):
        logger.info(f"DataFlow core directory is ready at {core_dir}")
        return

    if any(core_dir.iterdir()):
        raise RuntimeError(
            f"DataFlow core directory is incomplete at {core_dir}; refusing to merge into it. "
            f"Restore {', '.join(_REQUIRED_CORE_DIRS)} or move the incomplete directory aside."
        )

    import os
    if os.environ.get('DATAFLOW_TEAM_WORKER'):
        # Copy only installed, credential-free templates. No interactive CLI or downloads.
        import shutil
        import tempfile
        from dataflow.cli_funcs.paths import DataFlowPath
        stage = Path(tempfile.mkdtemp(prefix='.core-', dir=core_dir.parent))
        try:
            for source, destination in ((DataFlowPath.get_dataflow_pipelines_dir(), stage),
                                        (DataFlowPath.get_dataflow_example_dir(), stage / 'example_data'),
                                        (DataFlowPath.get_dataflow_playground_dir(), stage)):
                shutil.copytree(source, destination, dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns('.DS_Store', '__pycache__', '*.pyc'))
            if not dataflow_core_ready(stage):
                raise RuntimeError('Installed DataFlow templates are incomplete')
            core_dir.rmdir()  # Only the empty destination established above may be replaced.
            stage.replace(core_dir)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
        return

    logger.info(f"Initializing DataFlow core directory at {core_dir}")
    try:
        subprocess.run(
            [sys.executable, "-m", "dataflow.cli", "init"],
            cwd=core_dir,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"DataFlow core initialization failed in {core_dir}. "
            "Fix the active Python environment and retry."
        ) from exc

    if not dataflow_core_ready(core_dir):
        raise RuntimeError(
            f"DataFlow initialization completed but {core_dir} is incomplete; "
            f"expected: {', '.join(_REQUIRED_CORE_DIRS)}"
        )

    logger.info(f"DataFlow core directory initialized at {core_dir}")
