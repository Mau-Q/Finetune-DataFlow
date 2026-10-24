"""Read-only compact host snapshot; never launches or resumes computation."""
import json
import re
from pathlib import Path
from run_gpu1_cohort import HOST_RUN, LOG


def rows(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


def main():
    events = rows(LOG/'events.jsonl')
    current = next(r for r in reversed(events) if r['event'] == 'start')['label']
    root = HOST_RUN/'gpu1-core8-20261024'
    result = {'operation': current, 'training_complete': [], 'evaluations': {}}
    for i in range(8):
        name = 'G%02d'%i
        folder = root/name/'attempt1'
        if (folder/'audit.json').exists():
            result['training_complete'].append(name)
        if current == name+'-train':
            updates = [r['step'] for r in rows(folder/'events.jsonl') if r['event'] == 'optimizer_step']
            result['optimizer_step'] = max(updates or [0])
            result['completed_scoring_passes'] = len(rows(folder/'scores.jsonl'))
    for name in ['BASE']+['G%02d'%i for i in range(8)]:
        folder = root/'evaluation'/name
        count = len(rows(folder/'predictions.jsonl'))
        if count:
            result['evaluations'][name] = {'rows': count, 'complete': (folder/'metrics.json').exists()}
    log = LOG/(current+'.log')
    if log.exists():
        with log.open('rb') as handle:
            handle.seek(max(0, log.stat().st_size-65536))
            tail = handle.read().decode(errors='replace')
        scoring = re.findall(r'\[Selector step (\d+)\]:[^\r\n]*?(\d+)/256', tail)
        if scoring and current.endswith('-train'):
            result['last_scoring_progress'] = {'step': int(scoring[-1][0]), 'of_256': int(scoring[-1][1])}
    if events[-1]['event'] in ['stopped', 'stage_completed']:
        result['terminal_event'] = events[-1]
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
