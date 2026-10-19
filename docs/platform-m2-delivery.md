# M2 实施与验收记录

日期：2026-10-19。状态：M2 完成，M3–M6 尚未开始。WebUI 源码提交为 `0338205`；源码与工作区文档分别在 `codex/platform-m2` 分支提交。

## 交付范围

- 独立资源管理：沿用 Prompt Manager / My Templates 与 JSON Schema Manager，修复模板变量提取、嵌套 JSON 花括号和转义、缺失变量预览、保存失败提示。
- 后端 Schema 校验：使用现有环境已锁定的 `jsonschema 4.26.0`，在后端要求中声明 `jsonschema>=4.23,<5`。检查标准定义和示例，支持 draft-07 / 2019-09 / 2020-12、布尔 Schema 与文档内部引用；非法定义、示例约束失败、未定义内部引用或外部引用明确报错。
- 共用解析入口：静态校验、任务固定、同步执行与 Ray 执行共用资源解析与 Prompt 构造。两份 Pipeline 可引用同一个资源；Pipeline 持久化保留引用和字段绑定，不写入展开后的副本。
- 自定义模板接入：仅开放已核对契约的 `FormatStrPromptedGenerator.prompt_template`。画布参数面板支持选择模板、绑定变量到数据列、刷新列表；不支持的算子有明确说明，旧内置类与默认行为保留。Schema 只接入已声明的结构输出参数，不改造旧 13 算子的 QA 或评分协议。
- 任务固定：创建 queued 记录之前解析资源，保存 `pipeline_source_config`、`pipeline_config` 与 `resource_snapshots`。快照包含资源引用、位置、当时内容、更新时间与规范 JSON 的 SHA-256。删除或编辑资源不影响已有任务；缺失资源、变量绑定或不支持的契约在提交前失败。
- 历史查看：任务列表、状态和结果接口提供快照；任务面板可展开固定内容与哈希。旧任务没有快照时不补造历史内容。
- 文件持久化：Prompt 与 Schema 使用跨进程文件锁、原子替换及当前磁盘读取，避免更新丢失、缓存陈旧或损坏文件静默重建。

详细使用步骤和资源形状见 [Prompt / Schema 使用说明](../repos/dataflow-webui/docs/prompt-schema-resources.md)。

## 验证结果

| 验证 | 结果 |
| --- | --- |
| `./scripts/test-local.sh` | 核心 158 passed / 1 deselected；WebUI 149 passed / 7 subtests；扩展 30 passed |
| 新增 M2 测试 | 48 项，全部通过 |
| `npm run build` | 通过；保留既有 Sass 弃用与大 chunk 提示 |
| 工作区与 WebUI `git diff --check` | 通过 |

新增测试覆盖：变量重复和缺失、嵌套 JSON、字面量转义和非递归替换；Schema 标准定义和 minimum / pattern / additionalProperties 等约束、各支持版本和内部引用、非法 dialect；两实例读取、并发 CRUD、原子替换失败与坏文件；两份配置共享引用、更新与删除后的快照稳定性、内容哈希、资源正文中的引用形状字面量、非法绑定与不支持的算子；同步及异步提交在缺失引用时不写任务；同步返回固定配置与快照。

两套实际执行循环均以真实 `FormatStrPromptedGenerator` 加本地假服务进行离线验证：任务创建后删除资源，再用固定配置执行，模板渲染和 Schema 内容仍正确。Ray 测试直接调用其生产执行函数，没有启动 Ray 集群。没有调用外部模型，也没有进行真实训练数据生成或数据质量验收。

日志在本地忽略目录：`outputs/platform-m2-regression.log`、`platform-m2-resources.log`、`platform-m2-build.log`。最终完整回归包含全部 48 项新测试。

## 浏览器与实际 API

1. My Templates 创建带 `{question}`、嵌套 JSON 和 `{{literal}}` 的模板。缺少示例变量时显示 missing；填写后预览正确；保存后重新进入仍存在。
2. Schema 页输入非法 type，页面显示后端标准校验错误，确认按钮禁用；改为合法对象 Schema 和示例后保存成功，刷新后可展开查看。
3. 实际 API 创建两份临时 Pipeline，共享同一个 Prompt 和 Schema。保存、GET 重开均保留引用与绑定，没有保存展开副本。
4. 从画布自定义 Pipeline 列表打开其中一份，选中真实生成算子。模板下拉正确选中共享资源，变量绑定显示 `question → source`，Schema 下拉正确显示保存的资源。没有点击运行。
5. 验收后仅删除上述两份临时 Pipeline。保留标有“M2 验收”的 Prompt 与 Schema 各一份；未修改旧 Pipeline、历史任务、论文输入内容或默认数据集显示偏好。
6. 按用户要求关闭 `dataflow-m2` 与 M1 遗留的 `dataflow-m1` 测试浏览器，最终自动化浏览器列表为空。未关闭用户其他浏览器标签。

截图：[画布资源引用](../output/playwright/m2-canvas-reference.png)、[非法 Schema 提示](../output/playwright/m2-schema-invalid.png)、[Schema 保存后刷新](../output/playwright/m2-schema-saved.png)。截图为本地忽略产物，不随 Git 提交。

## 现场修复与备份

浏览器发现旧 Schema 页面与选择器请求 `/json_schemas/`，而后端只注册 `/json_schemas`。在实际应用的静态 UI catch-all 下，请求被截获，POST 返回 Method Not Allowed，GET 也无法取得资源列表。页面和选择器现统一使用规范地址，后端为带尾斜杠的旧地址提供兼容路由；新增带 StaticFiles 挂载的测试覆盖这条实际路径。普通测试应用的自动重定向不能证明这项兼容。

同时修复资源页错误消息被显示为 `[object Object]`、Schema 页面绝对定位覆盖导航，以及两条执行路径对 kwargs 键值列表展开不同的问题。同步提交现在执行刚固定的配置，并在响应中返回同一份快照；失败记录写回任务注册表。

开始前备份 13 份运行元数据及 SHA-256 清单，位于 `outputs/backups/platform-m2-20261019-143850/`。完成后核对全部备份文件哈希，并核对现场：原有 36 条 Pipeline、73 条输入记录、18 条任务 ID 全部保留；任务文件、Serving 文件和数据集显示偏好与备份字节一致。核对结果位于 `outputs/platform-m2-metadata-verification.json`。启动沿用既有逻辑刷新 API Pipeline / 算子缓存和部分时间戳，不清空注册数据。

核心 DataFlow、DataFlow-MM 与扩展源码未修改。工作区原有 `pipelines/SFT-PIPELINE-OPERATORS.md` 删除保持未提交。

## 后续实施

建议 M3 与 M4 连续实施，集中完成“任务运行 → 产物 → 草稿 → 发布与导出”的端到端验收，并分别记录各阶段完成条件。M5 仍单独实施；M6 的相关回归穿插进行，最终再做集成收尾。本次没有实施文本生成向导、恢复重跑、发布导出或多模态模板。
