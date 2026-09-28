"""Print an apply_patch document for exact, dependency-closed baseline functions.

Never imports the retired project or reads its credentials. Review/apply the
printed patch separately. Runtime uses only the vendored local modules.
"""
import ast
import hashlib
import json
from pathlib import Path

SOURCE = Path('/Users/rui/zhiyan/zhiyan-data-quality-center-retired-2026-09-19/01-code-and-history/working-tree')
TARGET = Path(__file__).resolve().parents[1] / 'extensions/paper-dataflow/paper_dataflow/baseline'
SPECS = {
    'token_contract': ('backend/app/think_reasoning/contracts.py', ['Qwen2BpeTokenizer', 'canonical_json', 'sha256_text', 'render_qwen36_parts'], 'import hashlib, json, re, unicodedata\nfrom functools import lru_cache\nfrom pathlib import Path\n'),
    'mixed_count': ('scripts/prepare_think_scaleup.py', ['word_compatible_mixed_count'], 'import re\n'),
    'quality': ('scripts/run_sft_quality_v3.py', ['generator_messages', 'verifier_messages', 'validate_generated', 'finalize_verifier_observation', 'aggregate_verifier', 'MAX_ACCEPTED_PER_PAPER'], 'import json, re\nfrom datetime import UTC, datetime, timezone\nfrom typing import Any\nfrom .token_contract import canonical_json, render_qwen36_parts, sha256_text\nfrom .mixed_count import word_compatible_mixed_count\n'),
    'production': ('scripts/run_sft_v3_production.py', ['derive_production_terminal_fields', 'checkpoint_rows'], 'from collections import Counter\nfrom typing import Any\nfrom . import quality as v3\n'),
    'usage': ('backend/app/chunk_to_qa/usage_telemetry.py', ['no_response_usage_observation', 'observe_provider_usage'], 'from typing import Any\n'),
    'gateway': ('backend/app/chunk_to_qa/model_gateway.py', ['ModelGatewayError', 'OpenAICompatibleModelGateway'], 'import hashlib, json, socket, threading, time\nimport urllib.error, urllib.request\nfrom collections import Counter\nfrom datetime import datetime, timezone\nfrom time import perf_counter\nfrom typing import Any, Callable\nfrom urllib.parse import urlparse\nimport httpx\nfrom .usage import no_response_usage_observation, observe_provider_usage\n'),
}


def main():
    files = {'__init__.py': '"""Frozen SFT-2000 baseline logic; provenance in vendor_manifest.json."""\n'}
    manifest = {}
    for module, (relative, roots, imports) in SPECS.items():
        path = SOURCE / relative
        source = path.read_text()
        tree = ast.parse(source)
        bindings = {}
        for node in tree.body:
            names = ([node.name] if isinstance(node, (ast.FunctionDef, ast.ClassDef)) else
                     [n.id for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)]
                     if isinstance(node, (ast.Assign, ast.AnnAssign)) else [])
            for name in names:
                bindings[name] = node
        selected, queue = set(), list(roots)
        while queue:
            name = queue.pop()
            if name in selected:
                continue
            selected.add(name)
            node = bindings[name]
            queue.extend(n.id for n in ast.walk(node) if isinstance(n, ast.Name)
                         and isinstance(n.ctx, ast.Load) and n.id in bindings and n.id not in selected)
        nodes = sorted({bindings[name] for name in selected}, key=lambda n: n.lineno)
        segments = []
        omitted = []
        for node in nodes:
            lines = source.splitlines(keepends=True)[node.lineno - 1:node.end_lineno]
            if module == 'gateway' and isinstance(node, ast.ClassDef) and node.name == 'OpenAICompatibleModelGateway':
                # Unused application-specific convenience method; complete() is exact.
                method = next(n for n in node.body if isinstance(n, ast.FunctionDef) and n.name == 'generate')
                del lines[method.lineno - node.lineno:method.end_lineno - node.lineno + 1]
                omitted.append('OpenAICompatibleModelGateway.generate')
            segments.append(''.join(lines).rstrip())
        content = ('"""Vendored exact source segments; see vendor_manifest.json."""\n'
                   'from __future__ import annotations\n' + imports + '\n\n' + '\n\n\n'.join(segments) + '\n')
        files[module + '.py'] = content
        manifest[module] = {'source': str(path), 'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                            'symbols': sorted(selected), 'omitted_unused_methods': omitted,
                            'segments': [[n.lineno, n.end_lineno] for n in nodes],
                            'vendored_sha256': hashlib.sha256(content.encode()).hexdigest()}
    files['vendor_manifest.json'] = json.dumps(manifest, indent=2, ensure_ascii=False) + '\n'
    print('*** Begin Patch')
    for name, content in files.items():
        print('*** Add File: ' + str(TARGET / name))
        print('\n'.join('+' + line for line in content.splitlines()))
    print('*** End Patch')


if __name__ == '__main__':
    main()
