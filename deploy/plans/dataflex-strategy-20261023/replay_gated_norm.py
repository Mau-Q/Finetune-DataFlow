"""Controlled launch-geometry sweep of one captured fused gated-norm packet."""
import argparse
import importlib
import json
from pathlib import Path

import torch
from safetensors.torch import load_file
import observed_run as observer
from probe_preselection import digest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    observer.prepare_reproducibility({}, 'torch-math-cublas4096-v2')
    module = importlib.import_module('fla.modules.fused_norm_gate')
    metadata = json.loads((args.source/'norm-call.json').read_text())
    packet = load_file(str(args.source/'norm-inputs.safetensors'), device='cuda')
    tuner = module.layer_norm_gated_fwd_kernel
    while not hasattr(tuner, 'configs'):
        tuner = tuner.fn
    candidates = list(tuner.configs)
    records = []
    for config in candidates:
        tuner.configs = [config]
        tuner.cache.clear()
        outputs = []
        for _ in range(2):
            with torch.no_grad(), torch.autocast('cuda', dtype=torch.bfloat16):
                value = module.rms_norm_gated(**packet, bias=None,
                                             activation=metadata['activation'], eps=metadata['eps'])
            outputs.append(digest(value))
        records.append({'kwargs': config.kwargs, 'num_warps': config.num_warps,
                        'num_stages': config.num_stages, 'outputs': outputs})
    result = {'status': 'CONTROLLED_GATED_NORM_CONFIG_SWEEP',
              'packet_sha256': observer.sha(args.source/'norm-inputs.safetensors'),
              'source_sha256': observer.sha(Path(module.__file__)),
              'script_sha256': observer.sha(Path(__file__)), 'cases': records}
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result), flush=True)
