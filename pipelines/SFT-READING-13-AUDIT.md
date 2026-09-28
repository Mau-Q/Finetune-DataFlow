# LIMA 单片段 QA 审核（2026-09-28）

审核对象是 LIMA 第 10 页 Discussion 段生成的两条 QA，以及任务 `5879b99d0e3c` 的评分缓存。本次只核对已保存的 PDF、片段、结果和算子代码；没有模型请求、重新评分或修改阈值。结论仅适用于这两条样本，不能外推到整篇论文或 13 篇论文。

## 来源与逐条判断

输入是 [LIMA PDF](/Users/rui/Downloads/SFT-data-composition-reading/02_Zhou_2023_LIMA_Less_Is_More_for_Alignment.pdf) 的第 10 页。原文 Discussion 先指出人工构造 1,000 条精选示例耗费心力且难以扩大规模，随后指出 LIMA 相比产品级模型不够稳健，解码采样不佳或对抗性提示可能导致弱响应。缓存保留了 `source`、`source_page`、`raw_chunk` 和 `chunk_metadata`；生成的 `supporting_facts` 是短文本，没有精确原文偏移。该片段还包含 References，虽未直接污染这两条回答，却给生成器提供了与问题无关的内容。

| 样本 | 来源核对 | 多跳性与表述 | 审核意见 |
| --- | --- | --- | --- |
| 1：为什么少量精选示例的方法难以扩展？ | 答案中的示例构建成本与“难以扩展”直接对应 Discussion 原文；没有发现新增的具体事实。 | 基本是对同一句限制的改写，属于单跳解释。“巨大脑力劳动”比原文的 *significant mental effort* 稍强。 | 可作为“论文作者指出的限制”类阅读 QA；不应计作已经验证的多跳 QA。 |
| 2：为什么 LIMA 在扩展性和稳定性上有局限？ | 两项限制分别对应原文相邻表述；“弱响应”的触发条件也在原文中。 | 合并两项并列限制，没有必须通过中间事实才能推出结论的推理链。“稳定性”概括了原文的 *robustness*，但不够精确；“不如产品级模型”是作者的相对判断，不能从本段得出独立实测结论。 | 来源基本支持，但问题和答案宜明确限定为“论文讨论部分的作者观点”；尚不能计作严格多跳。 |

## 评分与准入

两条缓存记录的四维评分均为 `4 / 5 / 3 / 0`（问题质量、回答对齐、回答可核验性、下游价值），`AlpagasusScore` 均为 `5`。当前规则要求五项全部至少为 4，因此两条均未准入，末端输出 0 条。**即使下游价值的 0 分后来能恢复为合格分数，可核验性 3 分仍会使两条落选。**

`downstream_value=0` 不能解读成模型明确给了零分：该维度保留了非空且大体肯定其用途的反馈。运行时的解析器只接受 `**Grading**: <数字>` 形式；没有匹配时写入 0。历史缓存没有保存该次模型原始回复，所以无法判明它究竟用了哪种评分格式，也无法恢复真实分数。随后代码已扩展为识别常见的评分行写法，并为将来的解析失败添加 `grading_parse_failed:` 标记；这些修改不改变这次历史结果。

`Text2QASampleEvaluator` 的四个评分提示只拼接问题和答案，**没有输入原文**。因此其“回答对齐”是答题对齐，其“可核验性”是从 QA 文本判断的可核验程度，均不等同于对 PDF 的证据审核。`AlpagasusSampleEvaluator` 在这条 Pipeline 中接收问题、原文片段与答案，但单个总体分数也不能替代逐事实来源核对。本次原文核对是单独进行的人工审查。

## 工程判断

这次试跑证明缓存续跑和末端零结果处理能够完成，但没有产出符合现有规则的 SFT 样本，也没有证明多跳生成质量。下一次扩大运行前，应先处理两个不同的问题：保存评分原始回复与解析状态，避免格式异常伪装成质量分数；明确多跳样本的验收定义，并检查生成问题是否真正需要连接多处证据。若目标只是论文观点阅读 QA，需要由项目负责人决定是否调整目标和准入标准；不能用放宽当前阈值代替这一决定。

证据文件：[单片段缓存](/Users/rui/Documents/DataFlow/data/sft-reading-13/lima-checkpoint-one.jsonl)、[评分缓存](/Users/rui/Documents/DataFlow/repos/dataflow-webui/backend/cache_local/5879b99d0e3c_output/dataflow_cache_step_step2.jsonl)、[评分解析代码](/Users/rui/Documents/DataFlow/repos/dataflow/dataflow/operators/core_text/eval/text2qa_sample_evaluator.py)。
