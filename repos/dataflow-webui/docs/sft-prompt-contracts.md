# SFT Pipeline 的 Prompt 接入与验收

本轮以现有论文文本 SFT（13 步）和图片 VQA 配置为范围。核心算子的注册名和默认 Prompt 不变；没有开启图片模型执行，也没有增加 DPO 生成流程。

## 接入清单

| 流程位置 | 参数 | 可编辑内容 | 固定边界 |
| --- | --- | --- | --- |
| KBCTextCleaner | prompt_template | 清洗规则，必须含 `{text}` | 输入来自原 input_key；追加 cleaned_start/cleaned_end 输出说明，保留原提取逻辑 |
| Text2MultiHopQAGenerator | prompt_template | 多跳问答要求，必须含 `{text}` | 固定系统协议；追加 question/answer/reasoning_steps/supporting_facts/type JSON 结构说明 |
| Text2QASampleEvaluator | question_quality_prompt_template | 问题质量评分标准，无变量 | 算子追加问题和答案；固定 Grading/Feedback、1–5 整数解析 |
| 同上 | answer_alignment_prompt_template | 答案对齐评分标准，无变量 | 同上 |
| 同上 | answer_verifiability_prompt_template | 可验证性评分标准，无变量 | 额外保留来源上下文和候选支持事实；不允许模板移除输入拼接 |
| 同上 | downstream_value_prompt_template | 下游价值评分标准，无变量 | 固定评分列、反馈列、解析失败及重试语义 |
| AlpagasusSampleEvaluator | prompt_template | 评分标准，无变量 | 固定指令/输入/回答拼接，首行有限 0–5 分，次行解释；非法分数保持失败 |
| 图片问题步骤 | resource_ref | 依据可见图像生成问题的规则 | 图像材料 ID 与输入语义固定；变量仅能绑定当前输入 |
| 图片答案步骤 | resource_ref + bindings | 回答规则，必须含 `{question}` | question 必须绑定上游问题；图片必须仍为当前图像 |

论文流程中的 MinerU4PDFParser、MinerU4PageExtractor、PaperEvidenceChunker、三个 PandasOperator、两个 GeneralFilter 和 HashDeduplicateFilter 无模型 Prompt，不增加模板选择。

图片结构检查与训练格式整理不增加 Prompt：前者使用 Schema，后者固定 messages + media_bindings。图片执行仍返回业务 409；配置接入不代表真实视觉生成已验证。

## 资源、任务与界面

- `/api/v1/prompts/contracts` 提供已接入的算子、参数位置、必需/可用变量和协议说明。
- 资源可独立创建；允许算子列表为空只表示不额外限制，不表示可以绕过位置契约。
- 核心通用 FormatStrPromptedGenerator 保留自由变量与数据列绑定；SFT 专用位置使用固定输入语义，不接受任意列绑定。
- 画布原生参数抽屉提供每个位置的模板选择、管理入口与协议说明。未接入位置明确提示保留内置模板。
- 流程持久化 user_prompt 引用；任务启动时一次读取并固定内容、位置、语言及哈希。同步和 Ray 执行器使用固定内容，资源后来改名、编辑或删除不改变已启动任务。
- 评分的四个位置可分别替换或恢复默认；资源详情只将未替换的位置计作默认模板用法。
- 新增可选构造参数通过实时算子详情读取，避免旧 ops 缓存遮住入口。离开画布时关闭参数抽屉；未填写的 SFT 可选服务和来源字段按未设置处理，必填字段仍校验。

这些限制保证程序接口和解析边界，不保证模型一定遵从文字指令，也不代替数据质量验收。没有改动原有分数阈值、筛选和去重规则。

## 隔离验收

从 WebUI 仓库执行，root 必须为新建的空目录：

```sh
PYTHONPATH=backend:/absolute/DataFlow/repos/dataflow \
  /absolute/DataFlow/.venvs/dataflow/bin/python backend/scripts/preview_sft_prompts.py \
  --root /absolute/empty-acceptance-directory --port 8006
```

打开 `/prompt-acceptance`。此环境使用独立数据库、Prompt/Schema/Pipeline 注册表和固定样本，无模型调用。四个最小文本流程覆盖七个位置；图片流程有独立图像、输出草稿和两份自定义模板。页面可验证当前已保存引用的渲染及快照，完整输入拼接和评分解析使用自动化离线测试覆盖。

重点检查：选择并保存后刷新仍保留引用；修改资源后新解析使用新内容；清洗/QA 模板缺少 text 时拦截；评分模板使用未知变量时拦截；恢复内置不会复用旧自定义内容；图片答案缺少 question 时拦截；图片原生画布可用下拉框选模板，切换模板后新增/移除的变量绑定随配置保存。已有任务的内容固定及两套执行循环由测试验证。

## 后续全库扩展

检查范围可以扩展至所有算子，但逐个确认是否调用模型、是否有实际 Prompt 消费点和稳定输入输出协议。依赖 LLM 不自动等于支持任意模板；解析、过滤、去重、格式整理等算子不需要 Prompt。后续按“生成/清洗 → 评分 → 特殊协议”分批接入，不能仅凭参数名批量开放。
