# M5 实施与验收记录

日期：2026-10-19。状态：M5 配置范围已完成，本地测试与浏览器验收通过；未做真实视觉调用，M6 最终集成尚未完成。WebUI 源码提交 `a5eacea`，源码和工作区文档分别在 `codex/platform-m5` 分支提交。

## 交付

- 新增「图片 VQA」入口，选择材料管理中的图片与已有图文 SFT 输出草稿，保存并重开独立配置。
- 四步为生成问题、生成答案、结构检查、训练格式整理。两步生成分别定义提示词，答案显式引用问题；支持用户 Prompt / Schema 引用、字段绑定、并发、超时及节点坐标。
- 同一配置驱动步骤展示与编辑；强制检查步骤顺序、字段依赖与语义、输出覆盖、资源存在性、模板变量、Schema 合法性、图片类型和目标草稿类型。非法更新不部分写入。
- 草稿可缺少服务、图片和输出目标，保存与运行检查分开。运行检查另验证图片文件及哈希。当前无视觉服务时显示“未配置视觉服务，未做真实运行验证”；任何服务引用均不能绕过未启用的独立 MM 执行桥接，提交返回 409，不创建任务。
- MM 步骤仅为模板元数据，不伪注册核心算子、不导入两套 DataFlow 包。输出声明共用 `messages+media_bindings` 契约，不声称已生成产物或修改目标草稿。

使用与存储说明见 [图片 VQA 模板](../repos/dataflow-webui/docs/multimodal-template.md)。

## 验证

- `./scripts/test-local.sh`：核心 158 passed / 1 deselected；WebUI 205 passed / 7 subtests；PDF 扩展 30 passed。
- 最终补充训练输出固定字段与非 Prompt 步骤绑定检查后，WebUI 全量复核 207 passed / 7 subtests，其中 M5 新增 20 项。
- `npm run build` 通过；保留既有 Sass 弃用、大 chunk 提示。两仓库 `git diff --check` 通过。
- 测试覆盖配置保存、文件存储重开、无服务暂存、非法修改原子失败、字段重命名与依赖、用户资源及删除引用、图片漂移、错误输出草稿、填写服务仍被拦截，以及 API 保存/读取/检查/拒绝提交。测试中的核心 operator/task registry 置空，配置路径无需核心注册或任务调度。
- Playwright 浏览器实际选择已有验收图片与图文草稿，修改并发为 2、问题节点 X 为 45，保存后刷新重开，图片、输出目标、参数与布局均保留。检查显示结构通过、无视觉服务；提交显示拒绝原因。保留一份明确标为“M5 验收 · 图片 VQA 配置（未运行）”的配置，未新增任务或训练样本。

日志：`outputs/platform-m5-regression.log`、`outputs/platform-m5-webui-tests.log`、`outputs/platform-m5-build.log`。浏览器截图：`output/playwright/m5-saved-reopened.png`；重开状态文本：`outputs/platform-m5-browser-snapshot.txt`。这些为本地忽略产物。

## 数据与边界

实施前在 `outputs/backups/platform-m5/` 备份 32 份现有 JSON 及 SHA-256 清单。核对原有 36 条 Pipeline 无缺失、新增或内容变化，仅 21 条内置记录因开发服务重载刷新 `updated_at`；两个算子缓存也按原逻辑刷新。其他已备份 JSON 字节未变。比对见 `outputs/platform-m5-metadata-verification.json`。新增多模态配置使用独立文件，没有覆盖旧注册配置。

核心 DataFlow、DataFlow-MM 和 PDF 扩展源码未改。工作区原有 `pipelines/SFT-PIPELINE-OPERATORS.md` 删除保持未提交。没有视觉 API 调用、本地模型下载、GPU 搭建、MM 全量依赖安装或本地假 API 试跑。真实文本小 PDF 与真实视觉运行继续待验；本次不作数据质量结论，也不把阶段回归称为 M6 最终交付完成。
