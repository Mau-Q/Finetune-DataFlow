# 当前论文切分方案

用户决定不做切分器对照，直接选择适合论文 SFT 的方案。当前采用 **结构优先、长正文递归细分**，2026-09-22 生效。原 SFT 生成方法 A/B 对照保留。

依据是论文已有 MinerU 结构，不必重新调用语义或大模型寻找所有边界。Chonkie 官方将 RecursiveChunker 推荐用于论文等结构化长文档：https://docs.chonkie.ai/oss/chunkers/recursive-chunker 。这是适用性判断，不是质量最优的实验证明。

## 已落地规则

1. 利用 MinerU 的章节标题和正文块，包括真实的 `paragraph_title` 类型。标题是章节边界，正文尽量随所属标题一起输出。
2. 同一章节可跨相邻物理页续接，页码保留为来源信息；未解析的页间缺口不拼接。图片可以插在续接段落中间，跳过图片证据时不切断前后正文。图像内容不用于纯文本问答，所有跳过块写入台账。
3. 以完整段落/结构块依次组合，正常上限为 **1024 个本地 Qwen2.5 tokens**。这给方法描述和上下文留出空间，是当前工程参数，不是声称最优长度。
4. 超长正文调用 **Chonkie 1.3.1 RecursiveChunker**，按段落、句子边界细分。显式传入本地 token 计数器，不采用字符数伪装 token 数。单句仍超限时保留并标记，暂不送生成。
5. 表格与独立公式是原子块；不截断以满足长度。超限内容保留、标记，等待单独处理。完整表格不保证可以脱离上下文回答问题。
6. 没有 80-token 最小门槛，没有英文大写开头要求，没有句末标点作为准入条件。没有固定重叠，减少重复证据；这不保证指代自动完整。
7. 每块保留分段来源映射：文档 SHA-256、物理页、块 ID、页内字符区间、chunk 内字符区间、坐标。正文不改写，各段均可与解析源逐字对应。

实现是本地 DataFlow 算子 `PaperStructuredChunker`，复用 Chonkie 递归算法，并适配 MinerU 结构和来源映射。**不是直接运行未修改的官方 KBCChunkGenerator，也不另写语义切分模型。** 本地官方 KBC 的 recursive 分支未传 tokenizer，而已安装 Chonkie 默认使用 character 计数；因此这里显式绑定 tokenizer。

## 当前开发包

活动入口为 `data/round1/active-preparation.json`，指向 `data/round1/development-structured-reviewed/`。旧窗口方案和最初结构化抽样保留为诊断记录，不应执行旧请求台账。

- 使用原来的 6 篇论文、第 2–3 页已有 MinerU ZIP；本次没有重新解析 PDF，也没有 embedding、生成 API 或训练调用。
- 所有结构化候选保存于 `all-chunks.jsonl`；输入筛选与切分分开。纯标题、公式解析已知问题均保留并标记。标记可生成只表示通过机械检查，仍需源文检查。
- 依据原 PDF 渲染和片段原文检查，选出 11 个开发输入，形成 22 个共同证据的 A/B 请求。开发选择文件为 `data/round1/structured-development-selection.json`，明确是 Agent 检查，不是 Human 验收或随机代表性评估集。
- FlowSlider 的完整引言跨第 2–3 页，现已续接。其他候选包括关键词和到第 4 页才结束的段落，因此该论文只选一个输入，不强行凑两个。确认阶段应使用全文解析，不能照搬第 2–3 页的调试抽样。
- 其他开发论文各选两个输入，覆盖数据方案、方法、公式和相关工作。没有根据 A/B 生成结果选择输入；目前没有生成结果。
- 旧 B 提示词的 400 混合单位限制保持不变。当前部分证据本身超过该值，运行后必须报告 SKIP/失败，不可暗改旧提示词或提前丢弃这些结果。
- 20 篇确认论文仍未使用。货币预算未固定，付费生成未启动。

两组分别完成各自生产流程，再用其他独立模型评估最终 SFT。原 DeepSeek V4 Pro 验证器保留在 B 的生产流程中，不作为最终质量裁判。具体约定见 `data/round1/evaluation-contract.json` 和 [实验说明](ROUND1-EXPERIMENT.md)。22 次仅为生成调用；原“总共 44 次”预算已撤回，生产验证／过滤和外部评估分别计费，待完整配置确定后重算总上限。

复现当前准备包（输出必须是新的目录）：

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venvs/dataflow/bin/python \
  -m paper_dataflow.pipelines.round1_recursive \
  --workspace "$PWD" \
  --output "$PWD/outputs/round1-structured-reproduction" \
  --selection-file "$PWD/data/round1/structured-development-selection.json"
```

验证入口：`scripts/verify-structured-round1.py`，检查所有块的来源覆盖、跨页映射、A/B 证据一致性、参数及代码/数据哈希。测试覆盖中文、小写、短段落、跨页、图片插入、标题、完整表格/公式、超长句子、重复句子和来源篡改。验证不等同于 SFT 质量提升。
