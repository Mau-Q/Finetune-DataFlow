"""Small synthetic DataFlex SFT checks; run inside the offline Linux training container."""
import argparse
import json
import math
import os
from pathlib import Path
import sys
import time

# Avoid the asynchronous compiler-worker stall observed in this reused image.
os.environ.setdefault('TORCHINDUCTOR_COMPILE_THREADS', '1')
import torch
import yaml


def prepare(root, model):
    from transformers import AutoTokenizer
    from llamafactory.data import get_template_and_fix_tokenizer
    from llamafactory.hparams import DataArguments

    tokenizer = AutoTokenizer.from_pretrained(model, local_files_only=True)
    args = DataArguments(template='qwen3_5_nothink', enable_thinking=False)
    template = get_template_and_fix_tokenizer(tokenizer, args)
    data = root / 'data'
    data.mkdir(parents=True, exist_ok=True)
    info = {}
    counts = []
    for length in [512, 4096, 8192]:
        records = []
        for index in range(2):
            instruction = '这是合成的环境测试材料。请只回答：检查完成。'
            answer = '检查完成。'
            unit = '这是测试段落，用于验证训练输入长度、参数更新和显存占用。编号为12345。\n'
            low, high = 0, length
            while low < high:
                mid = (low + high + 1) // 2
                text = instruction + '\n' + unit * mid
                prompt, response = template.encode_oneturn(tokenizer, [
                    {'role': 'user', 'content': text},
                    {'role': 'assistant', 'content': answer},
                ])
                if len(prompt) + len(response) <= length:
                    low = mid
                else:
                    high = mid - 1
            text = instruction + '\n' + unit * low
            # Fill the remaining budget with ordinary content rather than padding.
            while True:
                prompt, response = template.encode_oneturn(tokenizer, [
                    {'role': 'user', 'content': text + '测'},
                    {'role': 'assistant', 'content': answer},
                ])
                if len(prompt) + len(response) > length:
                    break
                text += '测'
            prompt, response = template.encode_oneturn(tokenizer, [
                {'role': 'user', 'content': text},
                {'role': 'assistant', 'content': answer},
            ])
            records.append({'instruction': text, 'input': '', 'output': answer})
            counts.append({'bucket': length, 'index': index, 'effective_tokens': len(prompt) + len(response),
                           'supervised_tokens': len(response), 'synthetic': True})
        name = f'synthetic_{length}'
        (data / (name + '.jsonl')).write_text(''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in records))
        info[name] = {'file_name': name + '.jsonl',
                      'columns': {'prompt': 'instruction', 'query': 'input', 'response': 'output'}}
    (data / 'dataset_info.json').write_text(json.dumps(info, indent=2))
    (data / 'synthetic-manifest.json').write_text(json.dumps(counts, indent=2))
    print(json.dumps({'prepared': counts}), flush=True)


def train(root, model, length):
    # Leave room for the resident workload on the shared GPU. This caps this process's torch allocator.
    torch.cuda.set_per_process_memory_fraction(0.60, 0)
    torch.cuda.reset_peak_memory_stats()
    output = root / 'output' / str(length)
    if output.exists():
        raise FileExistsError(f'Refusing to overwrite a previous attempt: {output}')
    candidate = yaml.safe_load(Path('/work/train.candidate.yaml').read_text())
    candidate.update(model_name_or_path=str(model), dataset_dir=str(root / 'data'),
                     dataset=f'synthetic_{length}', output_dir=str(output), cutoff_len=length,
                     per_device_train_batch_size=1, gradient_accumulation_steps=1, max_steps=2,
                     save_steps=2, logging_steps=1, overwrite_output_dir=False,
                     components_cfg_file=str(root / 'config/components.yaml'))
    config = root / 'config'
    config.mkdir(parents=True, exist_ok=True)
    (config / 'components.yaml').write_text('{}\n')
    path = config / f'train-{length}.yaml'
    path.write_text(yaml.safe_dump(candidate, sort_keys=False))
    started = time.time()
    from dataflex.cli import main
    sys.argv = ['dataflex-cli', 'train', str(path)]
    main()
    from safetensors import safe_open
    adapter = output / 'adapter_model.safetensors'
    with safe_open(adapter, framework='pt', device='cpu') as handle:
        nonzero_b = [name for name in handle.keys() if 'lora_B' in name
                     and bool(torch.count_nonzero(handle.get_tensor(name)))]
        if not nonzero_b:
            raise RuntimeError('No updated LoRA B tensor found')
    states = sorted(output.glob('checkpoint-*/trainer_state.json'))
    if not states:
        raise RuntimeError('Missing saved trainer state')
    state = json.loads(states[-1].read_text())
    losses = [row['loss'] for row in state.get('log_history', []) if 'loss' in row]
    if state['global_step'] != 2 or not losses or not all(math.isfinite(x) for x in losses):
        raise RuntimeError('Optimizer steps or finite training loss not verified')
    receipt = {'synthetic': True, 'cutoff_len': length, 'gradient_accumulation_steps': 1,
               'optimizer_steps': state['global_step'], 'losses': losses,
               'nonzero_lora_b_tensors': len(nonzero_b), 'adapter': str(adapter),
               'torch_peak_allocated_gib': torch.cuda.max_memory_allocated() / 2**30,
               'torch_peak_reserved_gib': torch.cuda.max_memory_reserved() / 2**30,
               'seconds': time.time() - started, 'gpu': torch.cuda.get_device_name(0)}
    (root / f'smoke-{length}.json').write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt), flush=True)


def reload_adapter(root, model):
    from transformers import AutoModelForImageTextToText, AutoTokenizer, BitsAndBytesConfig
    from peft import PeftModel
    torch.cuda.set_per_process_memory_fraction(0.60, 0)
    tokenizer = AutoTokenizer.from_pretrained(model, local_files_only=True)
    base = AutoModelForImageTextToText.from_pretrained(model, local_files_only=True,
        torch_dtype=torch.bfloat16, device_map={'': 0}, attn_implementation='sdpa',
        quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type='nf4',
                                              bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.bfloat16))
    loaded = PeftModel.from_pretrained(base, str(root / 'output/512'), is_trainable=False)
    text = tokenizer.apply_chat_template([{'role': 'user', 'content': '请回答：检查完成。'}],
                                         tokenize=False, add_generation_prompt=True, enable_thinking=False)
    inputs = tokenizer(text, return_tensors='pt').to('cuda')
    with torch.inference_mode():
        result = loaded.generate(**inputs, max_new_tokens=16, do_sample=False)
    receipt = {'adapter_reloaded': True, 'active_adapter': loaded.active_adapter,
               'generated_tokens': result.shape[1] - inputs.input_ids.shape[1],
               'synthetic_smoke_only': True}
    if receipt['generated_tokens'] <= 0:
        raise RuntimeError('Reloaded model produced no tokens')
    (root / 'adapter-reload.json').write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['prepare', 'train', 'reload'])
    parser.add_argument('--length', type=int, choices=[512, 4096, 8192], default=512)
    parser.add_argument('--root', type=Path, default=Path('/runs'))
    parser.add_argument('--model', type=Path, default=Path('/models/Qwen3.5-9B'))
    args = parser.parse_args()
    if args.command == 'prepare': prepare(args.root, args.model)
    elif args.command == 'train': train(args.root, args.model, args.length)
    else: reload_adapter(args.root, args.model)
