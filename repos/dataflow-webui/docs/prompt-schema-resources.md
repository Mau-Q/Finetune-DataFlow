# Prompt / Schema 资源管理

Prompt Manager 的 My Templates 与 JSON Schema Manager 可独立使用，无需先创建 Pipeline。内置 Prompt 的类、注册表和默认行为保持不变。自定义模板与 JSON Schema 各自保存在 `backend/data/prompts/user_templates.json`、`backend/data/schemas/schemas.json`；写入使用文件锁和原子替换，损坏文件会明确报错，不会清空重建。

## 默认列表与详情

两个管理器均默认显示“我的”，包含自己创建的资源及自定义流程实际使用的资源；与完整的“内置”库分栏，允许同一内置资源出现在两个页签。资源按引用 ID 去重，不复制、不改变所有权。列表仅显示名称、用途/功能、来源、使用的自定义流程数量；变量、源码、Schema、字段、示例与更新时间在详情查看。可组合搜索、用途、功能、算子与 Pipeline 筛选。

“我的模板”和“我的 Schema”的 Pipeline 下拉框只显示“文本 SFT”“图像 SFT”两个入口，按配置标签与步骤结构归组，不按历史配置名称猜测。验收、试跑和历史配置保留为详情中的使用记录，不单独列入筛选。内置页只列系统自带的预置 Pipeline，按 PipelineRegistry 的 api 标签及 api_pipelines 路径规则识别，不混入个人配置或平台的两个 SFT 模板。切换页签会清除不适用的流程选项。

“此流程使用”统计已保存配置中的显式引用，以及已核实的算子默认/固定 Prompt。“适用于此流程”按已接入算子和 Schema 参数匹配候选，不把可选项当成实际用法。用法代表当前保存配置，不代表流程已经运行。

文本 SFT 显示清洗、多跳 QA、四维评分和 Alpagasus 评分共七类 Prompt。默认映射依据 KBCTextCleaner、Text2MultiHopQAGenerator 的构造函数，默认映射依据 Text2QASampleEvaluator._build_prompts 与 AlpagasusSampleEvaluator.__init__；显式替换可选 Prompt 后不再统计被替换的默认项。图片 SFT 显示问题/答案 Prompt，结构检查计入 Schema，格式整理不虚构 Prompt。

详情按流程和步骤列出显式/默认/固定用法、Prompt 构造参数、算子 init/run 参数或图片步骤输入/输出及绑定，凭据字段隐藏。共享资源只保留一行，参数不同的使用位置分别保留。“我的”详情默认只列自定义流程，选择 SFT 入口后只列这一类流程；内置页可查看全部配置中的用法，并可跳转到流程。

内置 Prompt 包含注册的 Python Prompt 类和图片 SFT 问题/答案模板。Python 类只读，可查看源码及参数、填写构造和 build_prompt 参数预览；预览不调用模型。将预览另存为我的模板得到固定文本，需自行添加变量。文本模板可直接复制后编辑。

内置 Schema 提供文本 SFT、多轮文本 SFT、图文 SFT、文本 DPO、图文 DPO 与图片 VQA 问答输出六种版本化结构参考。它们只读，可复制为个人资源。结构规则不代替媒体存在性或回答差异检查，也不会自动应用到导入流程。图片结构检查下拉框仅提供模型输出/通用 Schema，训练样本 Schema 可在管理页查看。

侧栏隐藏数据库管理入口；原有 `/m/dm` 页面和后端能力保留，未新增 SQLite 管理页面。

## 自定义模板与字段绑定

1. 在 My Templates 创建模板，例如 `根据 {question} 回答，输出 {"answer":"示例"}`。
2. `{question}` 是变量；JSON 对象可以直接写入。`{{literal}}` 预览和执行时显示为 `{literal}`。只支持简单变量名，不支持 Python 属性访问、下标、格式说明或表达式；替换不会递归处理变量值中的花括号。
3. 示例变量用于预览，缺少变量会显示提示。示例值不会作为正式运行的字段默认值。
4. 在画布中选中 `FormatStrPromptedGenerator`，打开参数面板，从“自定义模板”选择已保存的模板，为每个变量填写数据列名。可用“刷新”载入新建或修改的资源。
5. 可选的 allowed operators 是额外限制；留空仍只支持已接入的算子契约。`FormatStrPromptedGenerator.prompt_template` 支持任意字段绑定；文本 SFT 的清洗、多跳 QA、四维评分和 Alpagasus 已按位置接入，输入拼接和输出协议保留。图片 VQA 配置支持问题/答案模板。详细位置与限制见 [SFT Prompt 接入](sft-prompt-contracts.md)。

Pipeline 保存的形状如下，两份配置可以引用同一个 ID：

```json
{
  "name": "prompt_template",
  "value": {
    "ref": "user_prompt:tpl_XXXXXXXX",
    "bindings": {"question": "text"}
  }
}
```

兼容 `"user_prompt:tpl_XXXXXXXX"` 字符串形状；此时绑定来自原有 `run.input_keys` 对象或键值列表。保存、重开不会把引用展开为模板副本。新配置的静态检查会识别缺少变量绑定和不存在的数据列。缺失资源、未允许的算子、缺少变量绑定、保留变量名（`storage`、`output_key`、`input_keys`）在创建运行记录之前阻止提交。

## JSON Schema

创建或更新时由后端 `jsonschema` 标准实现检查 Schema 定义；填写示例时同时检查示例是否满足该 Schema。支持 draft-07、2019-09、2020-12；不声明 `$schema` 时使用 2020-12。支持布尔 Schema、文档内部引用、组合和标准约束。`format` 按标准默认作为注解，不额外启用格式断言。

引用限制为当前文档内的 `#` 引用；不解析外部资源。未定义的内部引用、错误类型或 required 定义，以及不满足 minimum、pattern、minLength、additionalProperties 等约束的示例都会被拦截。修改 Schema 后会重新检查已保存的示例；不再适用的示例需要一起修改或清空。

参数面板的 Schema 下拉框保存 `schema_ref:schema_XXXXXXXX`，只适用于算子已声明的结构输出 Schema 参数；也保留内联 JSON 的用法。Schema 不会自动改变专用 QA、评分或训练样本的协议，也不会为不支持结构输出的算子添加参数。

## 任务固定与历史查看

同步和 Ray 提交共用 `resolve_pipeline_resources`。提交时复制配置，一次读取每个引用，保存：

- `pipeline_source_config`：资源引用与字段绑定。
- `pipeline_config`：可执行的固定配置，含当时的模板与 Schema 内容。
- `resource_snapshots`：资源 ID、名称、步骤与参数位置、当时更新时间、实际内容及规范 JSON 的 SHA-256。

执行器使用固定内容，不再从当前资源库读取。编辑或删除资源不会改变已有任务；之后的新任务会使用新内容，或因引用缺失而被阻止。历史任务列表可展开查看固定内容及哈希；旧任务没有这项记录时不虚构快照。状态与结果 API 同样提供快照，供后续恢复功能接入。本阶段没有新增恢复或自动重跑功能。

## API

- `GET /api/v1/prompts/catalog`、`GET /api/v1/json_schemas/catalog` 返回标准化资源、来源、personal 展示范围、兼容算子和实际配置用法。
- `POST /api/v1/prompts/builtin-preview` 接收 name / init / variables，预览已注册 Python Prompt。
- `GET /api/v1/json_schemas?include_builtin=true` 在原有个人列表上增加内置 Schema；省略此参数保持旧接口行为。

- `GET/POST /api/v1/prompts/user`；`GET/PUT/DELETE /api/v1/prompts/user/{id}`。
- `POST /api/v1/prompts/user/preview`，返回 rendered / placeholders / missing。
- `GET/POST /api/v1/json_schemas`；`GET/PUT/DELETE /api/v1/json_schemas/{id}`。
- `POST /api/v1/json_schemas/validate`，使用 name / schema / example，只校验不保存。
- `POST /api/v1/pipelines/validate`，检查资源契约和字段流。
- 任务的 executions、status、result 接口提供 `resource_snapshots`。

沿用 WebUI 的响应封装：业务错误也可能返回 HTTP 200，必须检查 `success` 与 `meta.http_status`，不能只检查 HTTP 状态。

验证使用临时存储、小型数据和本地假服务；两套实际执行循环均有离线覆盖，不代表真实模型生成或质量验证。使用真实模型、配置文本生成向导和收集产物属于后续阶段。
