# 13 篇 SFT 论文：PDF → 多跳 QA → SFT 候选 Pipeline

2026-09-28 创建并保存到本地 DataFlow-WebUI。13 篇全量版**已注册、尚未执行**；单篇 LIMA 和单块接续的执行记录见文末。

## 算子决策

```json
{
  "ops": [
    "MinerU4PDFParser", "MinerU4PageExtractor", "PaperEvidenceChunker",
    "KBCTextCleaner", "Text2MultiHopQAGenerator", "PandasOperator",
    "PandasOperator", "GeneralFilter", "Text2QASampleEvaluator",
    "AlpagasusSampleEvaluator", "GeneralFilter", "HashDeduplicateFilter",
    "PandasOperator"
  ],
  "field_flow": "source → parsed_document → source_page → raw_chunk → cleaned_chunk → QA_pairs → question/answer → four Text2QA scores + AlpagasusScore → instruction/input/output",
  "reason": "现有 MinerU 4 算子在本机处理 PDF、页码和来源位置；后续复用官方清洗、生成、评价、筛选和去重算子。使用官方中文多跳 QA 提示词，不加入自定义生成或审核提示词。"
}
```

## 输入和输出

输入清单：[documents.jsonl](../data/sft-reading-13/documents.jsonl)，每行一份本地 PDF 的绝对路径 `source` 和文件名 `source_name`。13 篇论文共 298 页；已核对文件均存在，第一页有可读取文本。源目录为 `/Users/rui/Downloads/SFT-data-composition-reading/`。

解析阶段保存 PDF 快照及 SHA-256、解析 ZIP 和日志；逐页提取保留页码与块坐标；分块结果保留 `raw_chunk` 和 `chunk_metadata`。清洗结果另存 `cleaned_chunk`。生成器将嵌套 `QA_pairs` 展开成独立的 `question` 和 `answer`。最终保留完整审核字段，同时增加训练字段：`instruction=question`、`input=raw_chunk`、`output=answer`。这里选择**给定论文片段回答**的训练形式。

## 流程与选择理由

1. **MinerU4PDFParser → MinerU4PageExtractor → PaperEvidenceChunker**：复用本项目已经接入的 MinerU 4 本地解析和证据分块路径。之前举例的官方 FlashMinerU 算子缺少本机运行所需 GPU 与模型，因此用户明确选择了此路径。这三步是本项目的适配算子。
2. **KBCTextCleaner**：按官方提示词生成清洗副本；原文仍留在 `raw_chunk`。
3. **Text2MultiHopQAGenerator**：英文分句配置配合官方中文提示模板，从清洗片段生成多跳问答；每个片段最多保留 2 条 QA。
4. **PandasOperator × 2 → GeneralFilter**：把 `QA_pairs` 展开并提取问题、答案，移除空问答。WebUI 的字段校验需要两次转换分别声明 `question` 与 `answer`；两次都使用官方通用表格算子。
5. **Text2QASampleEvaluator → AlpagasusSampleEvaluator**：前者保存四个维度的评分与反馈；后者将原始片段作为 `input` 参与整体评分。清洗和生成使用 Qwen 纯文本服务，评价使用 DeepSeek 纯文本服务；凭据由本地 WebUI Serving Manager 保存，不写入 Pipeline 文件。
6. **GeneralFilter → HashDeduplicateFilter → PandasOperator**：初始筛选规则是 Text2QA 四项分数和 Alpagasus 分数均达到 4，随后按问题与答案的组合精确去重，最后整理训练字段。这些阈值只是可编辑的初始配置，尚未验证。

WebUI 配置保存在 [sft-reading-13.webui.json](sft-reading-13.webui.json)，注册脚本为 [register-sft-reading-pipeline.py](../scripts/register-sft-reading-pipeline.py)，注册和静态校验结果见 [sft-reading-13.registration.json](sft-reading-13.registration.json)。在本地 WebUI 的 Pipeline 下拉列表中选择“**SFT 阅读论文 13 篇 · PDF → 多跳 QA → 评价筛选**”即可查看画布。

## 当前验证与执行边界

- 13 份 PDF 路径、文件可读性已检查；WebUI 输入数据集登记为 13 条。
- WebUI 静态字段校验通过；唯一警告把 `AlpagasusSampleEvaluator` 的 `input_output_key=answer` 误判为写回已有字段。源码实际将它作为输入读取，写出的是 `AlpagasusScore`。
- 已用合成行验证 `QA_pairs` 展开、评分过滤表达式及 SFT 字段映射；检查过程没有调用模型。
- **未运行 PDF 解析或任何模型调用**。对 298 页全量执行前，应先估算片段数、模型调用量与费用；单条样本质量、清洗保真度、评分有效性和最终训练效果均未验证。
- 该候选方案使用原生评价器的分数筛选，没有独立逐事实证据审核。带原文的整体评分也不等同于逐条事实核验。

再次执行 `./.venvs/dataflow/bin/python scripts/register-sft-reading-pipeline.py` 会复用同一路径的数据集并更新同名 Pipeline，不会执行数据处理。打开 WebUI：`http://127.0.0.1:8000/`。

## 单篇试跑

已另建「**SFT 阅读论文单篇试跑 · LIMA**」，输入是 15 页的 LIMA 论文，其他 13 个算子、字段映射、评分规则和模型服务绑定与全量方案一致。独立输入清单为 [lima-one.jsonl](../data/sft-reading-13/lima-one.jsonl)，独立配置为 [sft-reading-lima-one.webui.json](sft-reading-lima-one.webui.json)。它在 2026-09-28 执行过一次，失败点与接续结果见下文。

在 WebUI 的 Pipeline 列表中选择「SFT 阅读论文单篇试跑 · LIMA」，确认起点数据集只有 1 条，再点右上角 **Save & Run**。按钮会先保存当前画布，然后开始 PDF 解析及 Qwen/DeepSeek API 调用。运行中可打开 **Executions** 查看状态，点击节点看中间结果，并在末端节点下载结果。单篇仍可能产生多个文本块和多轮模型调用；目前没有实测调用量或费用。

若需要重新登记这个单篇入口，执行 `./.venvs/dataflow/bin/python scripts/register-sft-reading-smoke.py`；该命令只注册和静态校验，不会执行 Pipeline。WebUI 内两条 Serving 的 API URL、模型名和密钥字段已填写，且四个 LLM 算子均绑定相应 Serving。Qwen 的清洗和问答生成、DeepSeek 的短提示测试及两项评价已在下面的受限任务中实际调用；这不能证明 13 篇全量运行的稳定性。

## 2026-09-28 受限执行与接续结果

1. 单篇任务 `9fc165914038`：PDF 解析 15 页，分成 33 块；Qwen 清洗完成。问答算子因 API 读取超时返回空响应，又将空值传入 JSON 解析而失败。清洗后的 33 行保存在 `repos/dataflow-webui/backend/cache_local/9fc165914038_output/dataflow_cache_step_step4.jsonl`，SHA-256 为 `d64f4135103c11050be26cc57e8b0464c86d24152e7bd3a7cf5d6b6b28c08be8`。
2. 修复问答算子的空响应处理，并让 `num_q=2` 在发请求前限制每块最多 2 个请求。单块接续任务 `382eb1ca7fad` 从清洗缓存第 22 号正文块生成 2 条完整 QA，保存在 `repos/dataflow-webui/backend/cache_local/382eb1ca7fad_output/dataflow_cache_step_step1.jsonl`；后续因 Ray 执行器未编译单个字符串形式的 `PandasOperator.process_fn` 而失败。
3. Ray 执行器改为与同步执行器共用动态函数编译逻辑。无模型任务 `b5f5508a6c18` 从上述 QA 缓存完成展开与空问答过滤，得到 2 行独立问答。DeepSeek Serving 的单条短提示测试返回非空响应。
4. 评价任务 `5879b99d0e3c` 从这 2 行继续，两个评价器均完成；两行的四维分数均为 `4/5/3/0`，Alpagasus 分数均为 `5`。`downstream_value=0` 伴随非空反馈，应视为**评分格式解析异常或不确定**，不能解读为模型明确给出的 0 分。两行的可核验性为 3，按预设的全部维度至少 4 分规则，确实没有通过筛选。此时 JSONL 空结果丢失列名，使原末端字段整理报 `question` 缺失。
5. 末端字段整理已改为兼容空表；无模型任务 `6fda542e1755` 从评分缓存执行筛选、去重、字段整理，三步均完成，最终 **0 条通过**。没有放宽评分阈值，也没有把失败或空结果写作合格 SFT 样本。

本轮是**一个文本块**的工程链路验证，不代表整篇 LIMA 或 13 篇全量质量。完整单篇再次点击 **Save & Run** 仍会从 PDF 开始新任务；受限接续入口分别由 [register-sft-reading-resume.py](../scripts/register-sft-reading-resume.py)、[register-sft-reading-postqa.py](../scripts/register-sft-reading-postqa.py) 和 [register-sft-reading-eval.py](../scripts/register-sft-reading-eval.py) 登记。运行缓存按任务保存，但 WebUI 尚无自动断点续跑。模型调用量和费用未取得权威账单数据，不能据此推算全量成本。

## 2026-09-28 第二个文本块端到端验证

选择 LIMA 第 6 页原始分块缓存的第 14 行（`chunk_index=1`），与上次第 22 行不同。该块讨论对齐数据的多样性、回答质量和数量消融。输入文件是 [lima-block14-raw.jsonl](../data/sft-reading-13/lima-block14-raw.jsonl)；上游原始分块缓存 SHA-256 为 `1e3244fce54c3e4e7ffd5dda93daffd476ef58b25dec5d2d5c5b266d946c156d`，独立输入 SHA-256 为 `48ea7302a0484b758c521690932a65b84e7a1b3f76cace3bcadb675e972bf92d`。这次从**原始文本块**开始运行清洗、生成、整理、双评价、筛选、去重和导出，共 10 个算子；PDF 解析、逐页提取和分块复用此前保存的结果，没有重跑整篇论文。

独立 Pipeline 的 [登记信息](sft-reading-lima-block14.registration.json) 和 [配置](sft-reading-lima-block14.webui.json) 已保存。任务 `02ffb4e53346` 于 11:05:56–11:06:53 完成，10 个算子均为 `completed`。清洗后生成 2 条 QA；整理与空问答过滤后仍为 2 条；Text2QA 四维评分分别为 `4/5/3/0` 和 `4/5/3/5`，Alpagasus 都为 5；按原定每项至少 4 分的规则，筛选、去重和导出后 **0 条准入**。中间结果保存在 `repos/dataflow-webui/backend/cache_local/02ffb4e53346_output/`。

两条问题都围绕“增加数量不一定优于提升多样性和质量”改写，没有实际连接后文的实验设置与对照结果，因此没有证明多跳生成能力。第一条答案把原文的 *might not* 表述成“不足以”，语气更绝对。第一条的下游价值记录为 0，但反馈文字肯定其用途，不能视为模型明确给了 0 分；第二条该项为 5。WebUI/Ray 进程于 10:46 启动，早于 11:00 修改的评分解析代码；这次运行没有出现新代码应写入的 `grading_parse_failed:` 标记，因此**不能作为解析修复已在 WebUI 生效的证据**。无论该项分数如何，两条的可核验性均为 3，本次零准入结论不变。

两个不同文本块连续出现“执行完成、没有达到多跳目标、零准入”。继续以同样配置抽第三块的决策价值很低；先停在这次验证。可选方向是保持配置仅修复运行环境中的评分解析版本、重新定义并验证多跳生成目标、或把这条流程明确定位为普通论文阅读 QA。解析修复能消除一类格式误读，但不能让单句改写自动成为多跳问答，也不能直接改变两条可核验性为 3 的结果；后两项属于目标和验收口径的选择，不随本次试跑自动改变。

## 2026-09-28 运行通路复核

本阶段的验收目标改为**确认工程流程运行且没有未说明的评分解析错误**，不以 QA 质量或最终准入条数作为流程成败。原始任务 `02ffb4e53346` 的 10 个算子全部 `completed`；零准入是预设筛选规则的正常空结果。需要单独修复的是评分解释：第一条 QA 曾得到“下游价值 0 分、反馈正向”，旧代码在没有解析到评分行时默认写 0，历史原始模型回复没有保存，不能断言其具体格式或实际分数。

同一条 QA 的一次 Serving 探针回复是标准 `**Grading**: 4`，新旧解析器都读出 4；探针本身没有复现历史异常。探针原始回复保存在 `outputs/sft-reading-13/block14-downstream-probe.json`。重载 WebUI 后，从原任务的两条 QA 缓存接续的任务 `482f97d8c605` 完成评价至导出 5 个算子。其第一条下游价值 0 分明确带 `grading_parse_failed:`，证明新解析器已生效，也证明模型首次回复仍可能不符合可解析格式。随后代码加入**每个解析失败评分最多重试一次**的边界，不从反馈文本猜测数字；重试仍失败会保留 `grading_parse_failed_after_retry:`。

再次从同一 QA 缓存运行任务 `e354e3fbf4da`，5 个算子全部 `completed`：第一条下游价值首次解析失败、一次重试后得到 4 分并带 `grading_parse_retry_recovered:`；第二条该项为 5 分、无需重试。两条完整评分分别为 `4/5/3/4` 与 `4/5/3/5`，Alpagasus 均为 5。评分解析已无未说明的 0 分；末端仍为 **0 条**，因为可核验性均为 3，低于不变的准入门槛。该结果只证明本次单块运行通路和单次格式恢复有效，不证明所有模型回复都能被恢复，也不代表 QA 质量通过。接续入口见 [登记信息](sft-reading-lima-block14-eval.registration.json)和[配置](sft-reading-lima-block14-eval.webui.json)。

任务 `e354e3fbf4da` 的 Ray worker 日志进一步记录了首次失败回复的评分行：`**Grading**: [4]`。模型把提示词里的 `[1-5]` 占位格式部分照搬到了输出；旧解析器和第一版扩展解析器都不接受方括号，因而出现“反馈正常但分数记 0”。已在解析器中加入 `[4]` 这种明确评分行的识别，并保留一次有界重试来应对其他格式异常。这个根因证据属于新任务；历史任务未保存原始回复，不能据此断言历史回复一定也是方括号格式。

方括号解析的本地回归测试已通过；随后重载本地 WebUI，`/api/v1/datasets/` 返回 HTTP 200。由于没有再次要求模型生成同样的异常格式，“新进程实际收到 `[4]` 并在第一次解析中通过”仍是测试覆盖的代码路径，而非额外一次实测模型回复。

## 2026-09-28 单页 PDF 13 算子全链路

为验证**PDF 起点至最终导出在同一个任务中完成**，从用户下载的 LIMA 原论文提取第 6 页为独立单页 PDF；提取件与原页的文本层逐字一致，原论文路径、第 6 页和原件/提取件 SHA-256 保存在 [输入清单](../data/sft-reading-13/lima-page6-smoke.jsonl)。这是有界工程试跑件，不替代原始论文。独立 [Pipeline 配置](sft-reading-lima-page6-smoke.webui.json)、[登记与结果](sft-reading-lima-page6-smoke.registration.json)保留原 13 算子和评分门槛，仅将 PDF 解析输出目录隔离。

任务 `e17dba33b33b` 的 13 个算子全部 `completed`：**1 页 PDF → 2 个文本块 → 4 条 QA → 4 条完成双评价 → 3 条通过原规则并导出**。四维评分 16 项全部是 1–5 范围内的可解析数字，没有 `grading_parse_failed`、`grading_parse_failed_after_retry` 或重试标记。导出 3 行均有非空 `instruction/input/output`，并保留原论文路径和 `original_page_number=6`；提取件在新 PDF 中的页码为 1。最终 JSONL 位于 `repos/dataflow-webui/backend/cache_local/e17dba33b33b_output/dataflow_cache_step_step13.jsonl`，SHA-256 为 `582674182e0f8be297e94cc424f8709e57aa1b31a4b8fce06b18ee851a880e63`。

这是**流程通路成功**：PDF 解析、模型服务、评分解析、空/非空筛选、去重和导出在一次任务中衔接完成。它不是多跳 QA 质量、3 条候选适合训练、13 篇全量稳定性或模型输出格式永远稳定的证明。未来规模化运行仍需记录评分原始回复与解析状态，并按失败率设停止阈值，避免把无法解析的评分混同为模型真实给出的低分。
