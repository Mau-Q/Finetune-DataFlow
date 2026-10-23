"""Real Qwen single-forward weighting diagnostic, without optimizer updates.

This isolates two weight functions on the same loss graph. It does not repair or
claim equivalence of separate 24-update training trajectories.
"""
import argparse
import hashlib
import json
import time
from pathlib import Path

import torch
from transformers import AutoModelForImageTextToText, AutoTokenizer, BitsAndBytesConfig
from peft import PeftModel, prepare_model_for_kbit_training, set_peft_model_state_dict
from safetensors.torch import load_file
from llamafactory.data import get_template_and_fix_tokenizer
from llamafactory.hparams import DataArguments
from dataflex.train.weighter.custom_weighter import CustomWeighter
from dataflex.train.weighter.loss_weighter import LossWeighter
from dataflex.utils.loss_utils import per_sample_loss_from_logits

ROOT = Path('/runs/strategy-20261023')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(attempt):
    if not attempt.startswith('attempt') or not attempt[7:].isdigit():
        raise ValueError('Invalid attempt')
    folder = ROOT / 'paired-forward-probe' / attempt
    folder.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    torch.cuda.set_per_process_memory_fraction(.42, 0)
    torch.cuda.reset_peak_memory_stats()
    pointer = json.loads((ROOT / 'G06/successful-attempt.json').read_text())
    control = Path(pointer['observation_dir'])
    batches = [json.loads(line) for line in (control / 'consumption.jsonl').read_text().splitlines()]
    batch = next(item for item in batches if item['micro'] == 9)
    wanted = [item['sample_id'] for item in batch['items']]
    metadata = [json.loads(line) for line in (ROOT / 'data/metadata.jsonl').read_text().splitlines()
                if json.loads(line)['official_split'] == 'train']
    by_id = {}
    for task in sorted({row['task'] for row in metadata}):
        task_metadata = [row for row in metadata if row['task'] == task]
        samples = [json.loads(line) for line in (ROOT / 'data' / (task+'.jsonl')).read_text().splitlines()]
        assert len(task_metadata) == len(samples) == 64
        by_id.update(zip([row['_instance_id'] for row in task_metadata], samples))
    tokenizer = AutoTokenizer.from_pretrained('/models/Qwen3.5-9B', local_files_only=True)
    template = get_template_and_fix_tokenizer(tokenizer, DataArguments(template='qwen3_5_nothink', enable_thinking=False))
    encoded = []
    for identity in wanted:
        sample = by_id[identity]
        prompt, answer = template.encode_oneturn(tokenizer, [{'role': 'user', 'content': sample['instruction']},
                                                            {'role': 'assistant', 'content': sample['output']}])
        encoded.append((prompt + answer, [-100] * len(prompt) + answer))
    length = max(len(row[0]) for row in encoded)
    ids = torch.tensor([row[0] + [tokenizer.pad_token_id] * (length-len(row[0])) for row in encoded], device='cuda')
    labels = torch.tensor([row[1] + [-100] * (length-len(row[1])) for row in encoded], device='cuda')
    model = AutoModelForImageTextToText.from_pretrained('/models/Qwen3.5-9B', local_files_only=True,
                dtype=torch.bfloat16, device_map={'': 0}, attn_implementation='sdpa',
                quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type='nf4',
                    bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.bfloat16))
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True,
                                           gradient_checkpointing_kwargs={'use_reentrant': False})
    model = PeftModel.from_pretrained(model, pointer['output_dir'], is_trainable=True)
    snapshot = ROOT / 'paired-initialization-v2/adapter_init.safetensors'
    set_peft_model_state_dict(model, load_file(str(snapshot)), adapter_name='default')
    model.config.use_cache = False
    model.train()
    print('Model and shared adapter loaded', flush=True)
    torch.manual_seed(420009)
    torch.cuda.manual_seed_all(420009)
    outputs = model(input_ids=ids, attention_mask=ids.ne(tokenizer.pad_token_id).long())
    losses = per_sample_loss_from_logits(outputs.logits, labels, detach=False)
    print('One forward and differentiable sample losses complete', flush=True)
    del outputs
    params = [(name, value) for name, value in model.named_parameters() if value.requires_grad]
    assert params and all('lora_' in name for name, value in params)
    selected = [next(item for item in params if part in item[0]) for part in ['lora_A', 'lora_B']]
    uniform = CustomWeighter(strategy='uniform').get_weighted_loss(losses) / 2
    weighted = LossWeighter(strategy='linupper', delta=1.).get_weighted_loss(losses) / 2
    cu = torch.autograd.grad(uniform, losses, retain_graph=True)[0].detach().cpu().tolist()
    cw = torch.autograd.grad(weighted, losses, retain_graph=True)[0].detach().cpu().tolist()
    gu = torch.autograd.grad(uniform, [v for _, v in selected], retain_graph=True)
    gu_cpu = [v.detach().float().cpu() for v in gu]
    del gu
    repeat = torch.autograd.grad(uniform, [v for _, v in selected], retain_graph=True)
    repeat_cpu = [v.detach().float().cpu() for v in repeat]
    del repeat
    gw = torch.autograd.grad(weighted, [v for _, v in selected])
    comparisons = {}
    for (name, _), a, b, c in zip(selected, gu_cpu, repeat_cpu, gw):
        c = c.detach().float().cpu()
        assert torch.isfinite(a).all() and torch.isfinite(b).all() and torch.isfinite(c).all()
        # Declared before execution: same-graph repeat tolerance and effect floor.
        assert torch.allclose(a, b, atol=1e-4, rtol=.02)
        comparisons[name] = {'uniform_norm': float(a.norm()), 'linupper_norm': float(c.norm()),
                             'repeat_difference_l2': float((a-b).norm()),
                             'weight_difference_l2': float((a-c).norm()),
                             'weight_relative_l2': float((a-c).norm() / a.norm().clamp_min(1e-4))}
    assert any(value['weight_relative_l2'] > .02 for value in comparisons.values())
    assert all(abs(value-.25) < .005 for value in cu)
    assert abs(sum(cw)-.5) < .005 and abs(cw[0]-.25) > .025
    receipt = {'status': 'SAME_FORWARD_WEIGHT_GRADIENT_VERIFIED', 'optimizer_updates': 0,
               'sample_ids': wanted, 'micro': 9, 'forward_samples': 2, 'model_forward_calls': 1,
               'effective_tokens': sum(len(item[0]) for item in encoded),
               'losses': losses.detach().float().cpu().tolist(), 'gradient_accumulation': 2,
               'uniform_coefficients': cu, 'linupper_coefficients': cw,
               'gradient_comparisons': comparisons, 'uniform_repeat_atol': 1e-4,
               'uniform_repeat_rtol': .02, 'minimum_weight_relative_l2': .02,
               'initial_snapshot_sha256': sha(snapshot), 'data_manifest_sha256': sha(ROOT/'data-manifest.json'),
               'script_sha256': sha(Path(__file__)), 'seconds': time.monotonic()-started,
               'peak_allocated_gib': torch.cuda.max_memory_allocated()/2**30,
               'peak_reserved_gib': torch.cuda.max_memory_reserved()/2**30,
               'scope': 'Same initial adapter and single actual Qwen loss graph; separate training warmup mismatch remains unresolved'}
    (folder/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(receipt), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--attempt', required=True)
    main(parser.parse_args().attempt)
