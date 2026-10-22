# PDF 科研多任务 SFT：低成本生成与批量审核 v1

2026-10-22 已在本机平台创建并回读配置，未提交运行任务，未调用模型。

- Pipeline：`论文 PDF → 科研多任务 SFT · 低成本生成与批量审核 v1`
- ID：`3bc16630-8e85-43cd-97df-c40f8e86d5d1`
- 输入：`SFT 阅读论文 13 篇 · PDF 原件`，数据集 `a5f3dd5c5d`。只引用现有来源，不改动原 PDF。
- 生成服务：现有 `M6 · Qwen 文本与视觉`（qwen3-vl-plus），此流程只传解析文字。
- 审核服务：现有 `SFT阅读·DeepSeek纯文本`（deepseek-v4-pro）。
- 静态配置验证：valid=true，errors=[]，warnings=[]；这不等于 PDF、模型或训练链路已实跑。

## 节点与字段流

| 步骤 | 平台节点 | 输入 → 主要新增字段 |
| --- | --- | --- |
| 1 | PandasOperator / prepare_sources | source → source_path、document_id（PDF SHA256）、split、source_aliases |
| 2 | MinerU4PDFParser | source_path → parsed_document（解析产物与来源快照） |
| 3 | MinerU4PageExtractor | parsed_document → source_page（逐页结构块） |
| 4 | PaperStructuredChunker | source_page → raw_chunk、chunk_metadata；5800 token 结构切块 |
| 5 | PandasOperator / build_contexts | raw_chunk、chunk_metadata → unit_id、context、context_scope、source_map、context_valid、generation_input |
| 6 | GeneralFilter | 只放行 context_valid=true；暂缓记录留在上游缓存 |
| 7 | FormatStrPromptedGenerator | material=generation_input → generation_raw |
| 8 | PandasOperator / parse_candidates | generation_raw → keywords、candidates、invalid_candidates、candidate_count、review_input |
| 9 | GeneralFilter | 只放行 candidate_count>0；空生成与格式错误留在上游缓存 |
| 10 | FormatStrPromptedGenerator | batch=review_input → review_raw |
| 11 | PandasOperator / parse_reviews | 按 sample_id 配对 → 独立样本、instruction、input、output、review_status、review_reason |
| 12 | PandasOperator / export_results | 全部审核记录 → 审计与导出；仅 PASS 且精确去重后的样本进入后续平台收集 |

自定义变换集中在 `extensions/paper-dataflow/paper_dataflow/low_cost_sft.py`，通过现有 PandasOperator 调用；没有新增 Core/WebUI 算子。

## 生成与准入规则

采用 SciQAG 式的论文材料驱动生成，借鉴 SciRIFF 的多种任务及回答形式，并用简短读者背景和阅读目的增加任务差异；这是适配方案，不是两者的原样复现。不限定六类或固定比例，不强制每块生成四条。

同一论文的全部解析文字均合格且在 6000 token 内时合并，否则按章节/结构块生成。保留原解析文字，不用模型摘要压缩、不截断超长块。`paper_text` 只表示全部解析到的文字，不保证图像内容或 PDF 解析完整性。6000 是本地 Qwen tokenizer 的材料预算，不是完整生成/审核请求的 token 上限；审核还包含候选答案。

每个合格材料单元一次生成，最多四条候选；同一材料的合格候选合为一次审核请求。正常情况下每单元两个模型请求，不含服务层网络重试；这不是每篇 PDF 两次，长论文会拆成多个单元。没有自动语义重写、进化循环或审核重试。首次正式运行前仍应估算单元数量与总费用。

生成与评估提示词分别见 `generate.txt`、`review.txt`；已注册为平台受管模板，并各自绑定严格 JSON Schema。生成支持解释、抽取、实验解读、总结、比较、综合等开放任务形式；材料不足时可以返回空样本。当前输入按单篇组织，只能比较材料中已有的方法，不具备自动检索或跨 PDF 组卷能力。

审核维度为 grounded、task_fit、usefulness，各取 PASS/FAIL/UNCERTAIN：全部 PASS 才准入，有 FAIL 为 REJECT，其余为 REVIEW。未知或重复样本 ID、非法 JSON 等协议错误使整批待复核；单独缺少某个 ID 的审核，只使该样本待复核。不会用总分覆盖事实错误。

输入无 split 时默认 train；不会自动构造验证集。同一 PDF 分别标成不同 split 会报错。正式训练前应按论文先划分数据，避免同文段泄漏；近似重复版本识别暂未实现。

## 产物与审计

实际运行后，解析产物写入 `outputs/paper-multitask-low-cost/parsing/`；导出写入 `outputs/paper-multitask-low-cost/exports/<新UUID>/`，每次创建新目录：

- `sft.jsonl`：instruction/input/output 三字段，input 为该样本生成时使用的论文上下文。
- `audit.jsonl`：全部进入审核的候选及审核结果、拒绝原因、来源映射、精确重复状态。
- `record_mapping.jsonl`：准入样本到 SFT 行号、论文与来源片段的映射。
- `summary.json`：进入审核的候选数、准入数、审核状态和任务类型分布。

summary 不统计所有输入 PDF、被过滤上下文或空生成单元；这些需结合上游节点缓存查看，不应把 summary 当作全流程留存率统计。平台本来的任务产物和文本 SFT 收集机制继续使用。

## 保存与迁移

`pipeline.webui.json` 是本机配置快照，`registration.json` 和 `validation.json` 是保存与静态验证记录；不含 API 密钥。注册助手 `scripts/register-paper-multitask-low-cost.py` 只有登录、读取、创建资源和验证接口，没有运行接口。它拒绝覆盖与快照不一致的现有 Pipeline。

服务密钥不在这些文件里，引用的模型、数据集、提示词、Schema ID 只在本机有效。迁移服务器必须重建环境、上传 PDF、配置模型服务、重绑资源 ID 与绝对路径，不能直接复制本机虚拟环境或仅导入 JSON 就认为可运行。此助手仅支持本机开发网关，不是学校服务器的认证导入工具。

## 已做验证与未做验证

已验证平台保存后回读、12 节点字段依赖与必填参数检查、两节点提示词/服务/协议绑定，以及本地确定性处理测试。没有执行这条 Pipeline，没有实跑 PDF 解析、远程模型、GPU 或训练；模型输出协议兼容性、生成质量及总费用仍需之后获准的小样本运行核实。
