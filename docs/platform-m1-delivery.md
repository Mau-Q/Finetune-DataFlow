# M1 实施与验收记录

日期：2026-10-19。状态：M1 完成，M2–M6 尚未开始。

WebUI 实现提交：`6cfc51d`，分支 `codex/platform-m1`。工作区文档使用同名分支单独提交；核心 DataFlow、DataFlow-MM 和扩展源码均未修改。

## 本次交付

- 原始材料：PDF / 常见图片上传、本地文件登记并保存副本、内容去重、同名独立存储、分组和搜索、详情和可用预览、来源与说明编辑、原始材料及解析图片关系。
- 训练数据集：独立创建草稿，模态和训练类型分别保存，支持文本 / 图文 SFT、已有 JSON / JSONL 导入、字段集合、分页原始样本预览、图文媒体绑定及图片预览、导入记录。
- 数据检查：非法字段提示样本序号；媒体缺失、绑定冲突、文件变化明确失败；全批通过后才写入；重复文件不重复导入，相同样本跳过并提示数量。
- 持久化：`backend/data/library/materials` 与 `drafts` 独立于旧输入数据注册；原子 JSON 写入、线程和进程锁、保存文件哈希，损坏的元数据不静默重建。

使用步骤、支持的数据形状、文件限制、持久化目录与 API 见 [WebUI 使用说明](../repos/dataflow-webui/docs/data-library.md)。

当前只管理 PDF / 图片及这些格式的关联产物，公式和表格沿用原文件或解析图片，不运行新解析器。样本编辑、发布冻结和打包导出属于 M4；Prompt/Schema 解耦属于 M2；本轮没有执行 Pipeline 或调用任何模型服务。

## 自动验证

| 验证 | 结果 |
| --- | --- |
| `./scripts/test-local.sh` | 通过：核心 158 passed / 1 deselected；WebUI 92 passed / 7 subtests；扩展 30 passed |
| 最后补充单图 `image` 字段兼容后的 WebUI 全后端回归 | 93 passed / 7 subtests，其中 M1 新增 21 项测试 |
| 最终 `npm run build` | 通过；保留既有 Sass 弃用和大 chunk 提示 |
| 两个仓库 `git diff --check` | 通过 |

后端测试覆盖：文件类型和内容检查、PDF/图片持久化、同名独立存储、重复材料、本地路径保存副本、分组编辑、关联循环拦截、坏 JSON / 重复字段 / 非有限数值、批量校验回滚、文本与图文区分、单图及 messages 图片引用、媒体缺失与绑定冲突、并发导入、原子写失败和损坏元数据显式报错。API 测试使用正式异常封装，验证 `success=false` 的失败语义。

原始日志保存在本地忽略目录：`outputs/platform-m1-regression.log`、`outputs/platform-m1-backend-final.log` 和 `outputs/platform-m1-build.log`。

## 浏览器验收

使用 Playwright 操作实际构建后的页面与实际后端，使用专门的小型验收夹具，无模型响应模拟或真实生成：

1. 上传一份 PDF 与一张 PNG，查看详情及原文件入口；图片实际显示；刷新后仍能从列表打开。
2. 创建文本 SFT 草稿，导入一条 JSONL，查看原始字段与样本；再次导入同一文件出现重复提示；缺 output 的样本提示第 1 条不合规，已有行数仍为 1。
3. 创建图文 SFT 草稿；不提供媒体映射时提示媒体缺失；明确绑定已有图片 ID 后导入成功；刷新后仍有 1 条样本和关联图片。
4. 打开原有 Hub 和 Pipeline 模板列表，数据集、Pipeline、算子入口仍存在，没有运行或改写旧流程。
5. 最终 HTTP 检查：主页、旧 `/datasets/` 与 `/pipelines/`、新 `/library/materials` 与 `/library/drafts` 均返回 200，JSON 接口均 `success=true`。

[材料截图](../output/playwright/m1-materials.png)、[文本草稿截图](../output/playwright/m1-text-draft.png)、[图文草稿截图](../output/playwright/m1-vision-draft.png) 是本地验收产物，不随 Git 提交。页面布局已按实际截图检查；宽屏可见常驻导航，较窄视口沿用现有可收起的浮出导航。

验收示例保留在新材料库中，名称均以 `M1` 标记：两份材料、两个各含一条样本的草稿，不与旧实验注册混用。

## 备份及现场问题

实现前备份了 12 份运行 JSON / YAML 元数据及 SHA-256 清单，位于 `outputs/backups/platform-m1-20261019-140108/`。不包含密钥的内容输出到报告；原始备份只在本机保存，不纳入 Git。

最初完整回归与启动失败，原因是旧核心注册器将 `operators/.DS_Store` 和 `prompts/.DS_Store` 识别为 Python 模块。两份 Finder 元数据已移至上述备份下的 `registry-finder-metadata/`，附原路径与哈希清单，核心注册语义及源码未改动。清理环境障碍后完整回归通过。若 Finder 再次在这些目录生成同名文件，这个既有核心问题仍可能重现。

启动服务会按旧逻辑重扫注册数据。与备份比较：71 个旧数据集、36 条 Pipeline 注册记录的 ID 和配置均保留；变化仅为部分 `added_at` / `updated_at` 时间戳，以及自动重建的 `ops.zh.json` / `ops.en.json` 缓存。Serving、任务记录与 Prompt/Schema 原始元数据未发生变化。

工作区原有 `pipelines/SFT-PIPELINE-OPERATORS.md` 删除保持未提交，不属于本次变更。

## 2026-10-19 后续 UI 调整

根据用户确认，当前默认只显示「SFT 阅读论文 13 篇 · PDF 原件」（`a5f3dd5c5d`）；原有另 70 条输入记录及 2 个 M1 验收草稿改为隐藏，全部原记录保留。新添加数据默认可见。为浏览器验证新增的 2 条输入记录和 1 个图文草稿在验证后也隐藏，因此最终显示 1 个原始数据集，生成数据集列表暂为空。

原画布「数据集 → 添加」和原始数据集页的添加按钮接入共用表单，支持 PDF / 图片批量导入以及已有结构化文件。PDF / 图片形成兼容现有 Pipeline 的输入清单；没有启动 Pipeline 或调用模型。两个管理页面改为列表优先：原始数据集以文件列表和 PDF / 图片预览为主，生成数据集直接展示问答和图片；创建、导入、技术元数据与原始 JSON 均按需展开。图文导入可通过下拉框选择图片，减少手工 ID 输入。

发现论文清单的 13 条 `source` 仍指向已失效的 Downloads 路径。备份后改为当前确实存在的 `/Users/rui/Documents/论文资料/SFT-data-composition-reading/`；保留数据集 ID、论文顺序与文件名，并更新当前登记的文件哈希及来源目录。历史任务和缓存未改动。

备份为 `outputs/backups/dataset-ui-20261019-141655/`，包含原注册表、原清单、原草稿、SHA-256 清单及最终显示偏好。显示设置位于 WebUI 的 `backend/data/dataset_visibility.json`；清除对应隐藏 ID 可恢复显示。源码不写死本机的数据集 ID。

验证：`./scripts/test-local.sh` 通过（核心 158 项、当时后端 99 项、扩展 30 项）；最终补充 Parquet 空值与批内重复文件测试后，全后端 101 项通过，另 7 个 subtests 通过；最终前端生产构建通过。日志为 `outputs/dataset-ui-regression.log`、`outputs/dataset-ui-backend.log`、`outputs/dataset-ui-build.log`。

浏览器实际验证：原画布入口上传图片、新记录出现；独立原始数据集入口上传 PDF；13 篇论文列表及 PDF 原件可预览；图文草稿创建、图片下拉绑定、导入、图片真实加载、刷新保留；ID 与 JSON 默认折叠。验收截图位于 `output/playwright/dataset-ui-sources.png`、`dataset-ui-canvas-upload.png` 和 `dataset-ui-generated.png`。验收数据只是 UI 夹具，没有真实生成或质量结论。

## 2026-10-19 缩放与预览修正

数据管理页改为按内容面板实际宽度的容器查询布局；面板变窄时将数据集选择移到上方，进一步变窄时将文件列表移到预览上方。标题按钮允许换行，预览高度跟随可用视口。PDF 默认按预览宽度适配，并收起浏览器内置的缩略图侧栏。

前端生产构建通过；浏览器在 1600、1470、1280、1024、768、430 CSS 像素宽度下检查内容区、右侧按钮与页面边界，均无横向溢出；另以根元素 CSS zoom 125% / 150% 检查布局边界。这是布局缩放模拟，没有修改用户浏览器的缩放设置。1470 像素下实际截图确认 PDF 按宽度展示且缩略图收起。截图为 `output/playwright/dataset-scale-1470.png` 与 `dataset-scale-150-percent.png`。本次只改前端，没有重跑后端或模型流程。
