"""Validate exported Alpaca rows with the installed training template; no training."""
import argparse
import hashlib
import json
from pathlib import Path


def validate(source, model, cutoff):
    from transformers import AutoTokenizer
    from llamafactory.data import get_template_and_fix_tokenizer
    from llamafactory.hparams import DataArguments
    tokenizer = AutoTokenizer.from_pretrained(str(model), local_files_only=True)
    template = get_template_and_fix_tokenizer(tokenizer, DataArguments(template='qwen3_5_nothink', enable_thinking=False))
    counts = []
    for index, line in enumerate(source.read_text(encoding='utf-8').splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if any(not isinstance(row.get(k), str) for k in ('instruction','input','output')):
            raise ValueError('Invalid Alpaca strings at row '+str(index))
        if not row['instruction'].strip() or not row['output'].strip():
            raise ValueError('Empty instruction/answer at row '+str(index))
        text = '\n'.join(v for v in (row['instruction'], row['input']) if v)
        prompt, response = template.encode_oneturn(tokenizer, [
            {'role':'user','content':text}, {'role':'assistant','content':row['output']}])
        total = len(prompt)+len(response)
        if not response or total > cutoff:
            raise ValueError('Invalid training length at row '+str(index)+': '+str(total))
        counts.append({'row':index, 'tokens':total, 'supervised_tokens':len(response)})
    if not counts:
        raise ValueError('No training rows')
    return {'file_sha256':hashlib.sha256(source.read_bytes()).hexdigest(), 'rows':len(counts),
            'cutoff':cutoff, 'template':'qwen3_5_nothink', 'training_started':False, 'lengths':counts}


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('source', type=Path)
    p.add_argument('--model', type=Path, default=Path('/models/Qwen3.5-9B'))
    p.add_argument('--cutoff', type=int, default=6144)
    a = p.parse_args()
    print(json.dumps(validate(a.source, a.model, a.cutoff), indent=2))
