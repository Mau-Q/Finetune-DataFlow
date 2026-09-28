# LIMA 整篇论文 Pipeline 运行记录

日期：2026-09-28。目标是从一篇完整 PDF 出发，走通现有 13 算子 Pipeline，并保留逐步产物以理解数据流。此次运行不把模型评分等同于独立的 QA 质量验收。

## 输入与配置

- 原件：`/Users/rui/Downloads/SFT-data-composition-reading/02_Zhou_2023_LIMA_Less_Is_More_for_Alignment.pdf`，15 页，SHA-256 `759ddebaa24a03ee772a70d3a0ecc546f53310f209de0f8f6052a3dddb289144`。
- 单篇输入清单：`data/sft-reading-13/lima-full-paper-2026-09-28.jsonl`。Pipeline 配置和登记结果位于 `outputs/sft-reading-13/lima-full-paper-2026-09-28/`。这两个目录由工作区 `.gitignore` 排除；本记录可入 Git，原始输入与运行产物保留在本机。
- 独立启动的 WebUI 端口为 `8001`，加载 DataFlow `660d0e9` 和 WebUI `200e5ec` 的本地源码；原 `8000` 服务未用于本次任务。沿用先前配置：Qwen 负责清洗和 QA 生成，DeepSeek 负责四维与整体评分；每块最多 2 条 QA，五项分数均至少 4 才进入最终导出。没有改提示词、算子或筛选门槛。
- Pipeline ID `b84e20fe-6d75-4575-be68-33aef54e4396`，数据集 ID `d83b08f9b6`，任务 ID `653343528759`。配置静态校验为 `valid`；有一条沿用原配置的 `output_field_overwrite` 警告。

## 执行结果

任务从 15:27:09 运行到 15:51:55（北京时间），终态为 `completed`，13 个算子均为 `completed`。

| 步骤 | 算子 | 行数 |
| ---: | --- | ---: |
| 1 | MinerU4PDFParser | 1 |
| 2 | MinerU4PageExtractor | 15 |
| 3 | PaperEvidenceChunker | 33 |
| 4 | KBCTextCleaner | 33 |
| 5 | Text2MultiHopQAGenerator | 33 块，每块 2 条 QA |
| 6–8 | QA 展开、答案提取、空问答过滤 | 66 |
| 9–10 | Text2QA 四维评分、Alpagasus 整体评分 | 66 |
| 11 | 五项评分门槛筛选 | 34 |
| 12–13 | 去重、`instruction/input/output` 整理 | 34 |

15 页解析状态均为 `ready`。33 个分块的 `document_id` 均为原 PDF 的 SHA-256，且每个 `raw_chunk` 都与所属页的字符区间逐字一致。最终 34 行的 `instruction/input/output` 均非空，分别等于原 `question/raw_chunk/answer`，问答对均唯一。最终行来自 PDF 的第 1、2、4、6、7、8、9、10、11、13、15 页；其余页仍经过解析和分块，但没有样本通过最终评分门槛。

四维评分各 66 项、整体评分 66 项的 `parse_status` 全为 `parsed`，没有解析失败或恢复重试。各维度达到 4 分的数量分别为：问题质量 59、答案对齐 57、可核验性 40、下游价值 49、整体评分 64。五项同时达标 34 条；去重没有进一步删行。

## 产物与边界

- 可直接查看的 34 行导出：`outputs/sft-reading-13/lima-full-paper-2026-09-28/accepted-qa.jsonl`，SHA-256 `3ac82867efe8d6c75ad0fa3ecd89b2330712d3b79c98977728bf548ccde19899`。每行含 `instruction/input/output`、原件哈希、页码和字符区间、生成的推理步骤与支撑事实，以及五项分数。
- 机器可读摘要和每步 SHA-256：同目录 `run-summary.json`。13 个原始步骤缓存位于 `repos/dataflow-webui/backend/cache_local/653343528759_output/`；其中保留评分原始回复与解析状态。配置、登记信息分别为同目录的 `pipeline.webui.json` 和 `registration.json`。
- 这次证明一篇 15 页论文能够从 PDF 起点完成现有 13 算子并导出结果。34 条是**按现有模型评分规则通过**的数量，不代表人工事实审核、多跳要求或训练收益已通过。供应商权威账单和 token 用量未取得，不报告精确费用。

## 来源核验修正与重新评分

首次运行的可核验性评价只接收 `question` 和 `answer`，实际判断的是答案脱离上下文后是否容易核查，不能判断答案是否受论文支持。现已将该维度改为同时接收 `raw_chunk` 和 `QA_pairs.supporting_facts`；候选 supporting facts 被视为不可信模型输出，评分模型必须回到原文核对，并检查问题前提、答案中的全部实质性主张、跨表格列或跨参考文献合并。其他三个 Text2QA 评分维度的提示保持不变。

修正后的任务 `998d8c5e54eb` 复用原任务评分前保存的同一批 66 条 QA，没有重新解析、清洗或生成。5 个后半链算子全部 `completed`，四维评分和整体评分的解析状态均为 `parsed`。可核验性分布由原来的 `1:3、2:12、3:11、4:10、5:30` 变为 `1:7、4:2、5:57`，达到 4 分的数量从 40/66（60.6%）变为 59/66（89.4%）。按五项均至少 4 分的原规则，最终导出从 34/66（51.5%）变为 43/66（65.2%）：31 条保留、3 条移除、12 条新增。

新机制正确拦截了已确认的 weight decay `0`/`0.1` 冲突、把特定基线错误绑定到 GPT-4 替代实验、Shakshuka 与 Benadryl 表格列串接、把 Stanford Alpaca 作者误当作自对齐论文第一作者，以及不完整的 arXiv 编号；同义的 Figure 13 截断说明不再出现一条 5 分、一条 1 分的矛盾。仍有一个已知漏判：关于 Jason Wei 思维链论文的样本把前一条参考文献的 ICLR 会议信息接到后一条 NeurIPS 论文上，新可核验性仍给 5 分并进入最终结果。原因是 `raw_chunk` 在相邻参考文献之间缺少显式块边界；本次修正提高了来源核验能力，但尚不能替代人工审核或结构化 block 级证据。

重新评分缓存位于 `repos/dataflow-webui/backend/cache_local/998d8c5e54eb_output/`。最终 43 行缓存为 `dataflow_cache_step_step5.jsonl`，SHA-256 `993e7d4e63623f74006edb7b477a5c2c5b6229cbaaae7d79d3dfccc89b1b6477`。
