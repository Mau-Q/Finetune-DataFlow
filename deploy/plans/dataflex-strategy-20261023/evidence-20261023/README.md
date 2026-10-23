# 本轮证据的时间与适用范围

- 根目录中的 data/download manifest、初期 source/preflight、observed-gates 与 compact-evidence-manifest 是断网阶段留存。它们保留当时已知状态，不能代表恢复执行后的最终结果。
- `gates-readback/` 是恢复连接后首次回读的原始 receipt。其初始生成使用 LF 训练 prompt，后来实际发现输出思考标签；这些旧重载预测不满足非思考验收，不能用它们替代修正后的重载证据。
- `final/` 保存初轮学校汇总（提交 `94e1c17` 的历史快照）、实际依赖和源码身份、修正后的门测 receipt、两条人工核对输入及九组摘要、测试日志与文件哈希。该轮结论见 `final/results-summary.json` 和 `docs/training/dataflex-core8-results-20261023.md`。
- 最终八组训练与 576 条预测已验证的结论，当时包含明确未解决项：G06/G07 的独立训练预热梯度匹配失败；另一次同图诊断只证明权重改变梯度，不补成两条完整轨迹等价的证据。
- 所有尝试的完整数据、模型输出、梯度/消费记录和 adapter 留在学校；本地只保留紧凑证据，不保存整个测试集的原始预测。

- `gradient-resolution/` 为后续定位与修复的紧凑证据：7 次单步诊断、两组各 24 步完整确定性重跑、128 条新预测。最新配对结论以其中 `resolution-summary.json`、`resolution-verdict.json` 和 `docs/training/dataflex-g06-g07-gradient-resolution-20261023.md` 为准；没有改写旧轨迹或旧分数。
