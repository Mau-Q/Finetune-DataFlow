"""CPU-only identity capture for the tokenizer, actual LF template and dependencies."""
import hashlib
import importlib.metadata
import json
import time
from pathlib import Path

import llamafactory
import torch
from llamafactory.data import get_template_and_fix_tokenizer
from llamafactory.hparams import DataArguments
from transformers import AutoTokenizer


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    root = Path('/runs/strategy-20261023')
    model = Path('/models/Qwen3.5-9B')
    library = Path(llamafactory.__file__).parent
    tokenizer = AutoTokenizer.from_pretrained(str(model), local_files_only=True)
    template = get_template_and_fix_tokenizer(tokenizer, DataArguments(template='qwen3_5_nothink', enable_thinking=False))
    # Synthetic identity probe only; never enters frozen data or GPU training.
    prompt, answer = template.encode_oneturn(tokenizer, [{'role': 'user', 'content': 'Template identity probe.'},
                                                         {'role': 'assistant', 'content': 'Probe answer.'}])
    native_text = tokenizer.apply_chat_template([{'role': 'user', 'content': 'Template identity probe.'}], tokenize=False, add_generation_prompt=True, enable_thinking=False)
    receipt = {'lf_template_enable_thinking_attribute': template.enable_thinking,
               'lf_training_prompt_tail': tokenizer.decode(prompt[-30:], skip_special_tokens=False),
               'native_nothink_generation_tail': native_text[-100:],
               'native_nothink_probe_ids': tokenizer.encode(native_text, add_special_tokens=False),
               'captured_unix': time.time(), 'model_revision': 'c202236235762e1c871ad0ccb60c8ee5ba337b9a',
               'model_mount': str(model), 'template_name': 'qwen3_5_nothink', 'enable_thinking': False,
               'tokenizer_class': type(tokenizer).__name__, 'template_class': type(template).__name__,
               'eos_token_id': tokenizer.eos_token_id, 'pad_token_id': tokenizer.pad_token_id,
               'identity_probe': {'synthetic': True, 'training_data': False, 'prompt_ids': prompt, 'answer_ids': answer},
               'model_tokenizer_metadata_files': {p.name: sha(p) for p in model.iterdir()
                                                  if p.is_file() and p.suffix in ['.json', '.jinja', '.model', '.tiktoken']},
               'llamafactory_source_files': {name: sha(library / name) for name in
                                             ['data/template.py', 'data/formatter.py', 'data/processor/supervised.py',
                                              'data/collator.py', 'data/mm_plugin.py', 'train/sft/trainer.py', 'train/sft/workflow.py']},
               'packages': {name: importlib.metadata.version(name) for name in
                            ['dataflex', 'llamafactory', 'torch', 'transformers', 'peft', 'accelerate', 'bitsandbytes', 'datasets', 'safetensors']},
               'torch_cuda_build': torch.version.cuda,
               'scope': 'Identity capture only; no model weights loaded, no GPU validation implied'}
    (root / 'runtime-provenance.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'provenance_captured': True, 'packages': receipt['packages'], 'metadata_files': len(receipt['model_tokenizer_metadata_files'])}))


if __name__ == '__main__':
    main()
