"""Bounded read-only GPU/driver sampling; Python 3.6 compatible host script."""
import argparse
import json
import subprocess
import time
from pathlib import Path


def monitor(output, samples=3600, interval=5):
    output.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(samples):
        record = {'time': time.time()}
        for name, query in [('gpu', 'index,uuid,memory.used,memory.free,utilization.gpu'),
                            ('processes', 'gpu_uuid,pid,used_memory')]:
            option = '--query-gpu=' if name == 'gpu' else '--query-compute-apps='
            result = subprocess.run(['nvidia-smi', option + query, '--format=csv,noheader,nounits'],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    universal_newlines=True)
            record[name] = result.stdout
            if result.returncode:
                record[name + '_error'] = result.stderr
        with output.open('a') as handle:
            handle.write(json.dumps(record) + '\n')
        time.sleep(interval)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--samples', type=int, default=3600)
    parser.add_argument('--interval', type=float, default=5)
    args = parser.parse_args()
    if args.samples < 1 or args.interval < 1:
        parser.error('Positive samples and interval >= 1 required')
    monitor(args.output, args.samples, args.interval)
