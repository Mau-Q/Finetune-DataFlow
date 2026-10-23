# G06/G07 后续梯度定位与修复证据

本目录对应后续独立配对；初轮 `../final/` 和提交 `94e1c17` 的失败轨迹、分数保持历史身份。最新结论见 `resolution-verdict.json` 与 `resolution-summary.json`。

- `G06/`、`G07/`：实际配置、配对 sidecar、后端 receipt、执行源码/依赖 manifest、训练资源和原严格审计。
- `strict-verification.log`：正式修复配对的原审计直接通过。未使用 same-forward 兜底。
- `failed-hf-strict-verification.log`：通用 HF full_determinism 重跑失败日志。该尝试的 48 次更新仍计入预算。
- `failed-strict-warmup-comparison.txt`：仅严格算法设置在后续 4 步重复中失败，不能用早期两次单步的代表性梯度相同替代。
- `strict-math-verification.log`：组合协议的两次 4 步预热，16 对完整代表性梯度与 1,984 对全参数 optimizer 输入梯度完全一致。
- `strict-math-layer-comparison.txt`：首微批 32 个 decoder 输出和第 0 层所有叶子模块输出的完整哈希，在跨运行和 checkpoint 重计算之间相同。
- `runtime-inspection.txt`、`optimizer-hook-order.txt`：实际安装源码的 checkpoint/训练实现及 hook 位于裁剪之后、optimizer.step 之前的证据。不是模型训练通过证明。
- `mac-contracts.log`、`school-contracts.log`：24 项 CPU 回归，Mac 23 通过/1 PEFT 跳过，学校 24 通过。
- `final-state.json`：结束时容器、GPU、75 个 DataFlex 库文件及各次执行源码身份；`evidence-manifest.json` 绑定本地紧凑证据与对应工具源码。

正式修复为 sidecar 中的 `deterministic_execution: torch-math-cublas4096-v2`。它在 CUDA 初始化前固定 math-SDPA、workspace=:4096:8 和 PyTorch/cuDNN 确定性设置。YAML 中保留 `full_determinism: false`，防止 HF 通用 helper 覆盖 workspace；实际 deterministic algorithms 为 true。只切 math-SDPA 或只开严格算法设置均未稳定解决问题。尚未唯一定位某个底层 CUDA kernel。

正式修复训练没有启用额外的逐层输出追踪；逐层检查仅属于 4 步诊断。实际 source hash 和学校保留的历史源码版本见 `final-state.json`，不能把最终工具源码当成所有早期诊断的执行版本。最早 trace-A/B 的 runtime 未记录诊断 wrapper SHA，保留其脚本档案与实际 observer SHA，不能补称该 wrapper 已由当时 receipt 做哈希绑定。

完整原始数据、梯度、逐项模型哈希、adapter、checkpoint、全部 128 条新预测留学校：

- `/sharedata/home/huruiqian/DataFlow/runs/qwen35-9b/20261022-smoke/strategy-20261023/gradient-diagnosis-20261023`
- `/sharedata/home/huruiqian/DataFlow/runs/qwen35-9b/20261022-smoke/strategy-20261023/gradient-resolution-20261023`（通用 HF 方案失败）
- `/sharedata/home/huruiqian/DataFlow/runs/qwen35-9b/20261022-smoke/strategy-20261023/gradient-resolution-v2-20261023`（正式修复）

本地不保存完整测试集原始预测或第二份模型。紧凑结论区分实际观察、失败尝试、合成原语检查与尚未唯一归因的部分。
