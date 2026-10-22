#!/bin/bash
# Only inside the new dedicated platform container, never the original services.
set -euo pipefail
export PIP_NO_INDEX=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
python -m pip install --no-index --find-links /wheelhouse -r /work/platform-resolved.txt
# The image's old optional Mistral tokenizer breaks Transformers 5 processor
# class validation even for Qwen; this deployment does not need that extra.
python -m pip uninstall -y mistral-common
python /work/prune-inherited-extras.py /work/platform-resolved.txt
python -m pip check
python - <<'PY'
import importlib.metadata as metadata
import json
from pathlib import Path
import dataflow
import paper_dataflow
import numpy
import torch
from app.team_gateway import app
assert numpy.__version__ == '1.26.4'
record = {'numpy': numpy.__version__, 'torch': torch.__version__,
          'open_dataflow': metadata.version('open-dataflow'),
          'paper_dataflow': metadata.version('paper-dataflow'),
          'gateway_import': 'passed', 'pip_check': 'passed',
          'generation_model_called': False}
Path('/work/environment.json').write_text(json.dumps(record, indent=2))
print(json.dumps(record), flush=True)
PY
python -m pip freeze > /work/installed-requirements.txt
