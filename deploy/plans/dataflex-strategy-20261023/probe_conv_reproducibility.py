"""CUDA primitive diagnostic using Qwen's actual depthwise-convolution dimensions.

Synthetic tensors isolate the backend; this is not a training/data-quality test.
"""
import json
from pathlib import Path
import torch
from transformers import AutoConfig


def main():
    root = Path('/runs/strategy-20261023')
    folder = root/'gradient-diagnosis-20261023/conv-layout-primitive'
    folder.mkdir(exist_ok=False)
    config = AutoConfig.from_pretrained('/models/Qwen3.5-9B', local_files_only=True).text_config
    channels = 2*config.linear_key_head_dim*config.linear_num_key_heads + config.linear_value_head_dim*config.linear_num_value_heads
    kernel = config.linear_conv_kernel_dim
    consumed = json.loads((root/'gradient-diagnosis-20261023/trace-A/attempt1/consumption.jsonl').read_text().splitlines()[0])
    length = max(item['effective_tokens'] for item in consumed['items'])
    torch.manual_seed(420001)
    x = torch.randn(2, length, channels, dtype=torch.bfloat16, device='cuda').transpose(1,2).detach().requires_grad_()
    weight = torch.randn(channels, 1, kernel, dtype=torch.bfloat16, device='cuda')
    upstream = torch.randn_like(x)
    receipts = []
    for deterministic in [False, True]:
        torch.backends.cudnn.deterministic = deterministic
        output = torch.nn.functional.silu(torch.nn.functional.conv1d(x, weight, padding=kernel-1, groups=channels)[...,:length])
        gradients = [torch.autograd.grad(output, x, upstream, retain_graph=True)[0].detach().float().cpu() for _ in range(8)]
        first = gradients[0]
        receipts.append({'cudnn_deterministic': deterministic,
                         'repeat_bitwise_equal': [torch.equal(first,g) for g in gradients[1:]],
                         'max_absolute_differences': [float((first-g).abs().max()) for g in gradients[1:]],
                         'relative_l2_differences': [float((first-g).norm()/first.norm()) for g in gradients[1:]]})
    receipt = {'scope': 'Synthetic isolated convolution diagnostic; no optimizer/model updates',
               'shape': list(x.shape), 'stride':list(x.stride()), 'dtype': str(x.dtype), 'kernel': kernel, 'groups': channels,
               'torch': torch.__version__, 'cudnn_version': torch.backends.cudnn.version(),
               'cudnn_benchmark': torch.backends.cudnn.benchmark, 'tests': receipts}
    (folder/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt), flush=True)


if __name__ == '__main__':
    main()
