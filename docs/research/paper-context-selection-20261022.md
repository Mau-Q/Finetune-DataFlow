# 论文级小预算上下文选择：研究依据与本地验证

2026-10-22。用户预算：每篇至多 8 条候选，目标约 5 条合格；完整 PDF 全部解析。选择的是生成材料，不删除完整解析证据。不把 4 个上下文当作前四段或固定必须凑齐的数量。

## 研究决定

采用 **REFERENCE_ONLY**：借鉴覆盖、多样性和证据对齐目标，在现有 PandasOperator 中增加确定性变换，不引入新的模型服务或知识图谱系统。没有复制外部实现或提示词，因此没有引入其代码依赖和许可证。下列论文的任务与本项目不完全相同，不能据此宣布本项目达到 SOTA。

| 一手来源 | 可借鉴机制 | 适用边界 |
| --- | --- | --- |
| [SMART: Submodular Data Mixture Strategy for Instruction Tuning, Findings ACL 2024](https://aclanthology.org/2024.findings-acl.766/)，§4.8、§4.10；[作者代码](https://github.com/kowndinya-renduchintala/SMART) | 在样本级选择中比较 facility location，在任务级选择中比较 graph cut 与 log-det；代表性和多样性并不是同一目标 | 原文是已有指令样本的任务混合与筛选，不是论文原文块选择。其消融说明没有一种函数在所有层级都最优；本项目用 facility location 只是可审查基线 |
| [Evaluating Compound AI Systems through Behaviors, Not Benchmarks, Findings EMNLP 2025](https://aclanthology.org/2025.findings-emnlp.1314/)，§3.1、附录 A.4、算法 1 | 联合优化覆盖与多样性，按边际增益贪心选择；原文用嵌入 RBF 核的 log-det 加文档集合覆盖 | 原文先生成大量评测规格，再筛选；本项目先选择原文材料以限制付费调用，没有照搬其生成过量候选的机制 |
| [Explicit over Implict: Explicit Diversity Conditions for Effective Question Answer Generation, LREC-COLING 2024](https://aclanthology.org/2024.lrec-main.601/) | 显式控制位置、问题类型、实体差异，避免只依赖随机采样获得多样性 | 研究是 QA 数据生成；本项目开放式科研任务仍需审核，不能直接套用其下游效果数值 |
| [From Papers to Mechanisms: An Evidence-Grounded Knowledge Substrate for Scientific Language Models, arXiv:2610.06248v1](https://arxiv.org/abs/2610.06248)，§3 | 原文证据对齐、页码来源、证据不足时保留缺口 | 2026-10-05 预印本，面向科学检索与机制表示；其推理实现仍采用固定 top-k，本项目只参考证据约束，不引入领域机制 schema 或声称其证明了最优 packing |

检索到 2026 年长文档问答生成 VRQA 的出版方页面，但全文访问受限，未将搜索摘要作为可复现算法依据。这里选择的是已核对方法正文的来源，而非凭年份判定先进程度。

## 当前实现

`paper_dataflow.context_selection.propose_contexts` 针对每篇论文：

1. 原有解析质量门先行，排除已知不合格上下文；标题规则排除参考文献/致谢，低于 150 token 的前置信息暂不作为材料，精确重复原文只取一次。这些规则是当前工程启发式，并非论文提出的阈值。
2. 对全部可用块计算论文内 word TF-IDF 余弦矩阵，无联网、嵌入下载或额外商用 API 请求。按照标题规则标记概述、方法、实验、边界四种角色；一个块可有多角色，也可没有。角色只是索引提示，不能证明该块能独立支持对应问题。
3. 贪心最大化 `mean_j max_i∈S cosine(j,i) + 0.5 × covered_roles / available_roles`，至多 4 块，边际增益为零则提前结束。这里是词汇 facility-location 加角色集合覆盖，**不是原文的语义嵌入 log-det 复现**。该目标具有收益递减性质；任何近似保证只针对这个代理目标，不针对科学正确性或训练收益。
4. `budget_contexts` 通过 `select_paper_contexts` 标注选中状态，保留全部行、完整原文和来源映射；记录选择版本、排除原因、每步边际增益。生成输入最多 2 条/块；候选解析器必须同时设 `max_samples=2`，不能只靠提示词控制预算。重复 document/unit 身份直接报错，避免重复行突破预算。

适合现有节点 5 的绑定是先 `build_contexts(..., max_samples=2)`，再 `budget_contexts(..., max_candidates_per_paper=8, max_samples_per_context=2)`；节点 8 的 `parse_candidates` 同步使用 `max_samples=2`。保存的旧 v1 平台快照不会被此文档自动升级。上下文选择代码本地验证不等于已部署到学校平台。

## 前五篇缓存的离线检查

使用已经完成解析的五篇原文，不重新解析或调用商用 API。共 208 个完整准备上下文，其中原有质量门通过 185 个。一次本地选择用时约 **0.049 秒**，每篇提议 4 块。与“按文件顺序取前 4 个合格块”的对比：

| 论文 | 前四块的标题角色 | 选择后标题角色 |
| --- | --- | --- |
| Scaling Mathematical Reasoning | 概述 | 概述、方法、实验 |
| LIMA | 概述、方法 | 概述、方法、实验、边界 |
| FLAN Collection | 概述 | 概述、方法、实验、边界 |
| How Abilities Are Affected by SFT Data Composition | 概述 | 概述、方法、实验、边界 |
| SMART | 概述 | 概述、方法、实验、边界 |

这是选择器自身使用的标题代理指标，存在循环评价问题，**不是独立质量提升证据**。例如 LIMA 提议包含人工问答示例，Dong 论文提议包含附录结果：这些是否适合科研阅读 SFT 必须查看原文和候选，不能因为覆盖分数高就自动认为优质。缺失角色不以无关块补齐。

实际选择清单及来源位置保存在本轮输出 `outputs/paper-batch-20261022/context-selection-proposals.json`，完整上下文缓存仍在同目录。旧已付费响应另保留，不能因新算法无条件重跑。

## 验收边界

确定性测试覆盖：避免相同早期段落占满预算、跨论文分别预算、重复 ID 拒绝、原文/来源不变、无有效块时失败，以及选择顺序稳定。下一步质量验证应在同批原文和相同生成/审核模型条件下，比较证据支持、重复率、有效任务差异、通过率和每合格样本调用成本。当前未训练模型，未证明下游收益，也未因本次研究改变解析端并发。
