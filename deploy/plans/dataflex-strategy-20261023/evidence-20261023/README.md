# 本轮证据的时间与适用范围

- 根目录中的 data/download manifest、初期 source/preflight、observed-gates 与 compact-evidence-manifest 是断网阶段留存。它们保留当时已知状态，不能代表恢复执行后的最终结果。
- `gates-readback/` 是恢复连接后首次回读的原始 receipt。其初始生成使用 LF 训练 prompt，后来实际发现输出思考标签；这些旧重载预测不满足非思考验收，不能用它们替代修正后的重载证据。
- `final/` 保存最终学校汇总、实际依赖和源码身份、修正后的门测 receipt、两条人工核对输入及九组摘要、测试日志与文件哈希。最终结论以 `final/results-summary.json` 和 `docs/training/dataflex-core8-results-20261023.md` 为准。
- 最终八组训练与 576 条预测已验证的结论，包含明确未解决项：G06/G07 的独立训练预热梯度匹配失败；另一次同图诊断只证明权重改变梯度，不补成两条完整轨迹等价的证据。
- 所有尝试的完整数据、模型输出、梯度/消费记录和 adapter 留在学校；本地只保留紧凑证据，不保存整个测试集的原始预测。
