# G06/G07 梯度不一致：定位、修复与完整重跑

日期：2026-10-23（Asia/Shanghai）。**当前 node01 / GPU 2 / 固定软件栈中的配对问题已通过完整重跑解决。** 两组各完成 24 次更新，原严格梯度审计直接通过；两个新 adapter 各完成 64 条保存重载预测。没有关闭 dropout，没有放宽容差，也没有用 same-forward 诊断代替独立轨迹。

紧凑机器证据：[resolution-summary.json](../../deploy/plans/dataflex-strategy-20261023/evidence-20261023/gradient-resolution/resolution-summary.json)、[resolution-verdict.json](../../deploy/plans/dataflex-strategy-20261023/evidence-20261023/gradient-resolution/resolution-verdict.json)。[初轮报告](dataflex-core8-results-20261023.md) 与旧 adapter、分数和失败记录保留原样。

## 原因与有效修复

原执行协议只控制相同 LoRA 初始值、实际 batch 和 CPU/CUDA RNG，没有约束完整的计算后端。实际重复等权训练在应用权重之前就出现差异，因此原 G06/G07 差异不能直接归因于 linupper。

本轮验证有效的协议为 `torch-math-cublas4096-v2`：在模型加载与 CUDA allocator 初始化前，设置 `CUBLAS_WORKSPACE_CONFIG=:4096:8`、PyTorch deterministic algorithms=true、cuDNN deterministic=true/benchmark=false，并将 SDPA 固定为 math，关闭 flash/memory-efficient/cuDNN SDPA。该显式协议不设置 CUDA_LAUNCH_BLOCKING。初始 adapter、微批 RNG 控制继续保留，dropout 仍为 0.05。

这解决了当前运行栈的实际配对问题；**尚未把原因唯一定位到某个 CUDA kernel**。证据支持“原后端执行协议不足以保证配对可复现”，不支持声称某个 attention/卷积 kernel 单独有 bug，或只修改一个开关就必然解决。[PyTorch 复现说明](https://docs.pytorch.org/docs/stable/notes/randomness.html) 区分随机种子和确定性算法；本次结论依靠下面的实际重复与完整运行证据。

## 排查中排除的解释和失败方案

- 实际 checkpoint 是标准 reentrant PyTorch checkpoint，不是 Unsloth offload。
- 初始 LoRA 相同；五个完整留存参数/量化状态的早期诊断实例之间，3,046 项字节哈希相同。后续完整配对还核对全部 named buffers。
- 第 0 层八个 LoRA dropout 的首微批 RNG 和输入/输出前缀指纹相同，前向与重计算一致。此前缀最多 65,536 个元素，不能扩张成旧运行全部层的 dropout 掩码已核对。
- 单独切 math-SDPA 仍不一致。只开 deterministic algorithms、cuDNN deterministic、workspace=:4096:8，早期两次单步的代表性梯度曾完全相同，但后续 4 步重复又失败；该单步成功不足以证明修复。
- Transformers 通用 `full_determinism=true` 将 workspace 改为 :16:8 并开启 CUDA_LAUNCH_BLOCKING=1。按这套设置的两组各 24 步重跑仍失败，未进入重载评测；额外 48 次更新计入预算。
- 对同形状 BF16 深度卷积，以连续和转置布局各重复反向 8 次，cuDNN deterministic 打开/关闭均未复现差异。这是合成原语检查，不能作为模型单个 kernel 的根因证明。attention 原语初版因 bias dtype 不符在调用前报错，0 次 optimizer 更新，没有作为根因证据。

| 两次重复等权对照 | 首微批 LoRA B 相对 L2 差 | 第二微批相对 L2 差 | 这两个微批逐元素相同 |
|---|---:|---:|---|
| 默认 CUDA，单步 | 0.961138 | 0.018414 | 否 |
| 仅严格算法设置，早期单步 | 0.000000 | 0.000000 | 是 |
| 仅 math-SDPA，单步 | 0.226155 | 0.017693 | 否 |
| 仅严格算法设置，后续 4 步 | 0.020476 | 0.018002 | 否 |
| math-SDPA + 严格算法设置，4 步 | 0.000000 | 0.000000 | 是 |

组合协议的两次 4 步重复进一步核对了 8 微批 × 两个代表性 LoRA A/B 参数的 16 对完整梯度张量，以及 4 × 496 的全部 optimizer 输入梯度，均逐字节一致。首微批 32 个 decoder layer 的完整输出与第 0 层所有叶子模块输出，在跨运行、checkpoint 前向/重计算之间全部一致。该层检查仅覆盖首微批。

## 完整 24 步配对验收

正式修复重跑未启用上述额外的逐层输出追踪，避免将诊断追踪造成的同步误认为后端修复。仍记录代表性梯度、首五次更新全部参数梯度以及第 0 层 dropout 诊断。

- 全部初始参数、量化状态和缓冲区：3049 项哈希相同。
- 8 个预热微批 × 两个代表性 LoRA A/B 参数：16 对完整梯度张量逐元素相同，范数相对差为 0。
- 前 4 次更新前每次 496 个可训练参数的梯度哈希全部相同，共 1,984 对。这里是送入 optimizer 的累积、裁剪后梯度，不冒充每微批全部参数的原始梯度。
- 首个加权微批的两条逐样本 loss 完全相同：[2.376037359237671, 5.18017578125]；uniform/linupper 随后得到不同梯度，第 5 次更新前的梯度也实际不同。
- 原审计仍用 atol=1e-4、rtol=0.02；预热结果实际为精确相等。两组均完成 24 步、96 次样本展示、40 个加权微批；adapter 有限，LoRA B 实际改变。

| 首个加权微批参数 | uniform 梯度范数 | linupper 梯度范数 |
|---|---:|---:|
| LoRA B | 5.750201 | 4.782528 |
| LoRA A | 0.9910407 | 0.7668049 |

## 保存重载、资源与预算

两个新 adapter 使用同一组合协议，在原生非思考模板、greedy、max_new_tokens=256 和同一冻结测试集上各生成 64 条。用于验证新 adapter 保存重载与生成。没有把它们和初轮不同执行协议下的分数当作严格单变量比较，也不据单种子 24 步给策略排名。

| 新运行 | 训练 CLI 秒 | 峰值 allocated / reserved GiB | 分类 Acc / macro F1 % | NER micro F1 / JSON % | QA EM / F1 % | TLDR ROUGE-L % | cap / 空答 / think |
|---|---:|---:|---:|---:|---:|---:|---:|
| G06 | 208.5 | 16.413 / 17.947 | 81.25 / 76.00 | 26.93 / 93.75 | 37.50 / 56.01 | 26.51 | 1 / 0 / 0 |
| G07 | 209.6 | 16.413 / 17.947 | 81.25 / 76.00 | 29.91 / 100.00 | 37.50 / 58.51 | 28.02 | 0 / 0 / 0 |

本次新增 **119 次 optimizer updates、128 条预测**：7 次早期单步诊断 + 16 次两种 4 步配对诊断 + 48 次失败的通用 HF 确定性重跑 + 48 次正式修复重跑。连初轮全部额外工作，共 367 次更新、712 条生成记录（含旧门测）。所有失败尝试均未删除。

CLI 时间含加载、观察、保存和验证。没有单独测量各部分性能贡献。初轮数据局限继续适用：缺原始文档 ID；分类 13/16 为 Background；一条 NER 参考长于 256 生成预算；解析失败和 cap 未从分母删除。平台 SSH 执行器、P2/P3 不在本次通过范围。

## 实现与复核

`observed_run.py` 在 CUDA 初始化前读取配对 sidecar 的 `deterministic_execution`，设置实际后端并在 train_begin 核对。正式 YAML 特意保留 `full_determinism: false`，防止 HF 通用 helper 覆盖已选 workspace；这不代表实际确定性算法未开启。`prepare_pair_resolution.py` 会创建包含该 sidecar 的新目录，拒绝覆盖旧尝试。配置生成器也防止配对配置误开 HF 通用 helper。weighter 数学公式、loss 定义、冻结数据和基座模型权重均未修改。

学校目录：`/sharedata/home/huruiqian/DataFlow/runs/qwen35-9b/20261022-smoke/strategy-20261023/gradient-diagnosis-20261023`；首次通用方案为 `gradient-resolution-20261023`；实际修复为 `gradient-resolution-v2-20261023`。全梯度、初始状态逐项哈希、adapter、checkpoint 和 128 条预测留在学校，Mac 只存紧凑证据、脚本、配置和测试日志，没有下载第二份模型。

可在原容器 CPU 复核，不做模型前向或 optimizer 更新：

```sh
docker exec -e CUDA_VISIBLE_DEVICES= rui-dataflex-strategy-gpu2-20261023 \
  python /work/strategy-20261023/verify_pair_resolution.py \
  --root /runs/strategy-20261023/gradient-resolution-v2-20261023
```

CPU 回归共 24 项：Mac 23 通过、1 项因缺实际 PEFT 跳过；学校 24 项全部通过。另验证源码编译、diff 和实际部署脚本哈希，DataFlex 安装及平台 75 个库文件仍与初轮基线相同。未跑全仓回归，变更限独立实验工具。最早 trace-A/B 未在 runtime 记录诊断 wrapper SHA，保留档案与实际 observer SHA；后续诊断和正式配对均记录并核对实际 wrapper SHA。用户原有的 `pipelines/SFT-PIPELINE-OPERATORS.md` 删除继续保留，不纳入本轮提交。
