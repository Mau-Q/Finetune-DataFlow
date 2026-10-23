# 统一设置重跑：已按用户要求暂停

暂停时间（UTC）：2026-10-23T14:59:17.021473+00:00。本轮调度器及 G04 训练进程已发送 SIGTERM 并确认退出；GPU 2 容器当前只保留 sleep 主进程。GPU 2 实验容器和原 GPU 3 容器均保持 running，未停止容器、删除模型或修改其他任务。

| 项目 | 暂停时状态 |
| --- | --- |
| G00–G03 | 每组完成 24 次优化器更新，原训练机制审计通过；尚未重新评测 |
| G04 | 最后记录第 13 次更新；保留 checkpoint-12 和诊断日志 |
| G05 | 尚未开始训练 |
| BASE、G00–G05 新评测 | 尚未开始，新增预测 0 条 |
| G06/G07 | 保留此前通过配对梯度审计和重新加载评测的结果，未重跑 |

本轮新增已观测优化器更新为 109 次（96 + 13），不是六组全部完成。G04 checkpoint-12 保存了 adapter、tokenizer 和 trainer_state，但没有 optimizer 状态，不能将其描述为可精确恢复的完整训练断点。当前调度器也拒绝覆盖不完整 attempt；后续继续需要显式处理 G04 的新 attempt 或恢复方案。

统一协议采用 torch-math-cublas4096-v2，46 项共享配置核对一致。G00–G05 为 microbatch 1、梯度累积 4，G06/G07 为 microbatch 2、累积 2，均为有效 batch 4。

仍有未解决的数值限制：G01/G02 在选择前、初始参数哈希及所记录输入/RNG 对齐的检查中，首个 microbatch 代表性 B 梯度相对 L2 仍相差约 5.01%。未唯一定位根因，也未排除全部未记录运行时状态。此前 G06/G07 的已通过证据不因此改写；当前不能声称八组都实现严格可复现，也没有完整的新统一评测对比。

暂停证据：`deploy/plans/dataflex-strategy-20261023/evidence-20261023/uniform-core8/pause-receipt.json`，含 G00–G03 原审计和资源记录、进程退出与容器状态。远程运行根目录：`/sharedata/home/huruiqian/DataFlow/runs/qwen35-9b/20261022-smoke/strategy-20261023/uniform-core8-20261023`。

本轮脚本此前完成本机 27 通过 / 1 因缺少实际 PEFT 跳过、学校环境 28 全通过的 CPU 合约检查及语法检查。它们不代表未完成训练或评测通过。原用户改动 `pipelines/SFT-PIPELINE-OPERATORS.md` 的删除保留。
