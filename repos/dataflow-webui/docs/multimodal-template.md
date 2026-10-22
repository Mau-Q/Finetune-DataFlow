# 图片 VQA 模板

如需实际调用 API 验收图片 SFT/DPO，使用「Pipeline → 模板」中的「代表性图片 SFT」和「代表性图片 DPO」。
这两条走原生任务执行器，支持输出目录、运行记录和手动收录，无需本地模型；操作见
[四个代表性 API 流程验收](../examples/representative-training/README.md)。下文描述的是仍保留的 M5 配置草稿入口。

入口：画布顶部「Pipeline → 自定义 Pipeline → 图片 VQA」，或 `/#/m?workflow=multimodal`。点击节点使用原生参数面板编辑，原生「保存」固定参数与节点位置；图片、视觉服务与输出草稿从顶部设置链接或图片节点 Switch 配置。原 `/#/m/multimodal` 独立配置页继续兼容。

这是 M5 的配置功能。当前没有经过验证的视觉服务，也没有启用 MM 执行桥接；任何提交都会返回 409，不创建排队任务，不调用模型。填写视觉服务引用不会解除拦截。

## 配置与重开

1. 在「原始数据集」材料管理中导入图片；已有 PDF 页面图或解析裁图也可作为独立图片导入。本阶段不增加裁图策略。
2. 在「生成数据集」创建图文 SFT 草稿，或选择已有草稿作为未来输出目标。保存配置不会修改目标草稿内容。
3. 在「图片 VQA」选择图片、输出草稿，调整并发、超时、字段绑定和节点坐标。
4. 两个生成步骤分别定义问题与答案提示词。内置问题提示词要求只生成可由图片回答的问题；答案提示词通过 `{question}` 接收问题并要求依据图片回答。
5. 可以引用 Prompt Manager 中的用户模板和 JSON Schema Manager 中的 Schema。受限 Prompt 必须允许 `PromptedVQAGenerator`；模板变量必须绑定当前步骤可用字段，答案模板必须含有绑定到问题字段的 `{question}`。
6. 保存配置草稿，刷新后在配置列表中重开。缺少图片、输出目标或视觉服务允许暂存；无效引用、输入依赖、字段覆盖及非法参数会阻止保存，并保留旧配置。
7. 检查运行条件：结构有效与运行就绪分别显示。图片文件缺失或哈希变化也会报错。提交按钮用于显示明确的运行拦截原因。

四步顺序固定为生成问题、生成答案、结构检查、训练格式整理。可以修改中间输出字段，但必须同步更新下游输入及 Prompt 变量绑定；训练输出固定为 `messages`。输出契约为 `messages+media_bindings`，媒体通过材料 ID 显式关联，共用图文草稿与发布打包边界。此处保存的是未来产物契约，没有生成实际样本。

模板参考独立 DataFlow-MM 的 `image_vqa.py` 和 `PromptedVQAGenerator`，并改为两份明确提示词。MM 步骤是外部模板元数据，未注册到核心算子表，也不导入 MM 包。页面流程展示和编辑共用同一份 `config.steps`；模板通过薄适配复用原生 mainFlow、operatorNode 和参数面板；不会写入核心 PipelineRegistry，也不会查询或注册外部类到核心算子表。

## 存储与备份

配置位于 DataLibrary 根目录的 `multimodal_configs.json`（默认 `backend/data/library/multimodal_configs.json`）；使用现有 ResourceStore 的跨进程锁与原子写入。备份时连同整个 library、prompts 和 schemas 目录保存。配置保存资源引用，资源编辑会影响下一次结构检查；本阶段没有任务或资源执行快照。

API 前缀 `/api/v1/multimodal`：`GET /template`、`GET/POST /configs`、`GET /configs/{id}`、`GET /configs/{id}/check`、`POST /configs/{id}/submit`。配置不写入 PipelineRegistry，因此旧的核心同步和 Ray 执行路径不会拾取它。

未来实际启用前，需要独立进程、JSON 文件输入输出、视觉服务适配、运行资源固定和真实小样本验收；本轮未安装 MM 全量依赖、未下载模型、未搭建 GPU，也没有测试 API 的伪视觉试跑。
