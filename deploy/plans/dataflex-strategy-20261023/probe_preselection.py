"""Bounded actual-CLI warmup probe; stops before the first optimizer update.

Uses new attempt directories and the unchanged existing observer/backend policy.
Complete input and tensor hashes complement the older prefix-only dropout trace.
"""
import argparse
import functools
import hashlib
import json
from pathlib import Path

import torch
from transformers import TrainerCallback
import diagnose_pair_runtime as diagnostic
import observed_run as observer


def digest(value):
    t = value.detach().cpu().contiguous()
    return {'shape': list(t.shape), 'dtype': str(t.dtype),
            'sha256': hashlib.sha256(t.reshape(-1).view(torch.uint8).numpy().tobytes()).hexdigest()}


def describe(value):
    if torch.is_tensor(value):
        return digest(value)
    if isinstance(value, dict):
        return {str(k): describe(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [describe(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return {'class': type(value).__module__ + '.' + type(value).__name__}


class ProbeComplete(BaseException):
    pass


def main(config, folder, stop_micro, stop_step=None):
    original_install = observer.install
    diagnostic.original_install = original_install

    def install(cls, folder):
        current = diagnostic.enable_diagnostics(cls, folder, True, True, True)
        original_step = cls.training_step

        class StateCallback(TrainerCallback):
            def on_step_end(self, args, state, control, **kwargs):
                observer.emit(folder/'probe-updates.jsonl', {
                    'step': state.global_step,
                    'trainable_parameter_hashes': {
                        n: digest(p) for n, p in kwargs['model'].named_parameters() if p.requires_grad},
                })
                if stop_step is not None and state.global_step == stop_step:
                    observer.emit(folder/'probe-state.jsonl', {
                        'event': 'intentional_stop_after_optimizer',
                        'completed_optimizer_steps': state.global_step,
                    })
                    raise ProbeComplete()

            def on_train_begin(self, args, state, control, **kwargs):
                model = kwargs['model']
                observer.emit(folder/'probe-state.jsonl', {
                    'event': 'train_begin',
                    'module_training': {n: m.training for n, m in model.named_modules()},
                    'model_class': type(model).__module__ + '.' + type(model).__name__,
                    'probe_sha256': observer.sha(Path(__file__)),
                    'max_steps_unchanged': args.max_steps,
                })

                def before(module, args, kw):
                    if current.get('micro') != 1:
                        return
                    observer.emit(folder/'probe-model-inputs.jsonl', {
                        'module': type(module).__name__, 'training': module.training,
                        'grad_enabled': torch.is_grad_enabled(),
                        'args': describe(args), 'kwargs': describe(kw),
                        'rng': diagnostic.rng_signature(),
                        'autocast_cuda': torch.is_autocast_enabled('cuda'),
                        'autocast_dtype': str(torch.get_autocast_dtype('cuda')),
                    })

                model.register_forward_pre_hook(before, with_kwargs=True)

        old_init = cls.__init__

        @functools.wraps(old_init)
        def init(self, *args, **kwargs):
            old_init(self, *args, **kwargs)
            self.add_callback(StateCallback())

        @functools.wraps(original_step)
        def step(self, model, inputs, num_items_in_batch=None):
            micro = current.get('micro', 0) + 1
            if micro == 1:
                observer.emit(folder/'probe-inputs.jsonl', {
                    'inputs': describe(inputs), 'num_items_in_batch': describe(num_items_in_batch),
                    'values': {k: v.detach().cpu().tolist() for k, v in inputs.items() if torch.is_tensor(v)},
                })
            result = original_step(self, model, inputs, num_items_in_batch=num_items_in_batch)
            if stop_micro is not None and micro == stop_micro:
                observer.emit(folder/'probe-state.jsonl', {
                    'event': 'intentional_stop_after_backward', 'micro': micro,
                    'completed_optimizer_steps': self.state.global_step,
                    'trainable_parameter_hashes': {n: digest(p) for n, p in model.named_parameters() if p.requires_grad},
                })
                raise ProbeComplete()
            return result

        cls.__init__ = init
        cls.training_step = step
        return current

    observer.install = install
    try:
        observer.train(config, folder)
    except ProbeComplete:
        receipt = {'status': 'BOUNDED_PROBE_COMPLETED', 'stop_micro': stop_micro, 'stop_step': stop_step,
                   'reason': 'Intentional diagnostic boundary; not a completed full training run',
                   'config_sha256': observer.sha(config),
                   'probe_sha256': observer.sha(Path(__file__))}
        (folder/'probe-complete.json').write_text(json.dumps(receipt, indent=2)+'\n')
        print(json.dumps(receipt), flush=True)
    else:
        raise RuntimeError('Probe did not stop at its declared boundary')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--stop-micro', type=int, default=1)
    parser.add_argument('--stop-step', type=int)
    args = parser.parse_args()
    if args.stop_micro < 1 or args.stop_micro > 16:
        parser.error('stop-micro must be between 1 and 16')
    if args.stop_step is not None and not 1 <= args.stop_step <= 4:
        parser.error('stop-step must be between 1 and 4')
    main(args.config, args.folder, None if args.stop_step else args.stop_micro, args.stop_step)
