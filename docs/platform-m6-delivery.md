# M6 集成回归与交付记录

日期：2026-10-19。状态：M6 的本地集成与文档交付已完成，M1–M6 规划范围已收尾。真实文本小 PDF / 模型调用和真实视觉运行仍未验收，本次未产生新的模型生成数据或质量结论。WebUI 交付提交 `8c015ff`，实现基线 `a5eacea`；两仓库均在 `codex/platform-m6` 分支分别提交。核心 DataFlow 保持 `769a99e`，MM 保持 `1552534`。

## 交付范围

补齐 [本地平台使用手册](../repos/dataflow-webui/docs/local-data-platform.md)，涵盖启动、前端更新、页面入口、材料到发布的操作顺序、模型条件检查、资源快照、失败整批重跑、持久化目录、备份恢复及跨目录恢复限制。文档索引已接入，材料管理说明中“由后续 M4 实现”的旧状态也已更新。既有详细说明继续保留：[材料与草稿](../repos/dataflow-webui/docs/data-library.md)、[资源契约](../repos/dataflow-webui/docs/prompt-schema-resources.md)、[任务与发布](../repos/dataflow-webui/docs/text-generation-and-releases.md)、[图片 VQA](../repos/dataflow-webui/docs/multimodal-template.md)。

本轮未发现需要修改生产代码的集成失败，没有新增依赖、部署服务或改动生成算法。

## 当前重新执行的回归

| 命令 / 范围 | 本轮结果 |
| --- | --- |
| 工作区 `./scripts/test-local.sh`：核心 CPU | 158 passed / 1 deselected |
| 同一入口：WebUI 后端全量 | 207 passed / 7 subtests passed |
| 同一入口：PDF 扩展 | 30 passed |
| `frontend` 下 `npm run build` | 通过，4.03 秒 |
| 两仓库 `git diff --check` | 通过 |

保留既有 Sass 弃用、大 chunk、Python 弃用和 pytest 标记等警告；无本轮测试失败。此回归含同步/Ray 生产函数的离线测试、失败与恢复、输入/服务漂移、资源编辑/删除后的快照稳定性、发布和媒体完整性检查；未启动真实 Ray 集群或请求真实模型。日志：`outputs/platform-m6-regression.log`、`outputs/platform-m6-build.log`。

## 浏览器验收与证据

使用独立 Playwright 会话 `dataflow-m6`，连接当前 `http://127.0.0.1:8000/` 的构建产物。下列结果为本轮实际操作与文件校验，未沿用旧报告作为本轮通过证据。

| 验收项 | 本轮操作与观察 |
| --- | --- |
| 材料导入 | 导入专用单页空白 PDF `m6-material.pdf`，添加「M6 验收 · PDF 材料（未生成）」原始数据集，显示 1 条，并出现在文本向导选项。先选已导入文件时正确提示重复，未覆盖原材料。空白 PDF 只验证上传/预览/配置，不测试解析质量。 |
| 文本配置与画布 | 保存「M6 验收 · 文本配置（无服务未运行）」，ID `55f8605e-bae1-42b4-bc44-7e6118922298`。画布展示该材料与 13 步，执行保存再返回向导；同一 ID、13 步、批次选项保留。检查列出四个步骤缺少文本服务，提交被拒绝。 |
| 任务到草稿 | 打开已有 `864c7095f65c` 离线固定样本任务，在真实详情页面将训练产物收集到新建「M6 验收 · 离线产物集成草稿」。新增 1 条，第二次收集报错，没有重复新增。 |
| 发布与下载 | 发布该草稿 v1，通过浏览器下载 ZIP。随后在页面编辑回答，保存后再次下载 v1；两份 ZIP 字节完全一致。发布包 data.jsonl 与清单哈希一致。 |
| 图文可移植包 | 从已有图文 v1 页面实际下载 ZIP，消息 image_url 指向包内相对 `media/` 文件，媒体与数据哈希逐项匹配清单。此步骤复核已有导入/发布图文包，没有生成新图文样本。 |
| MM 保存与拦截 | 新建「M6 验收 · 图片 VQA（未运行）」，选择已有图片与图文输出草稿，并发 3、问题节点 X=65。保存、刷新并重新选择后全部保留。结构通过；检查与提交明确显示无视觉服务、独立 MM 桥接未启用；没有排队。 |
| 历史资源快照 | 通过生产 TaskRegistry 固定专用用户 Prompt 引用，随即将该验收记录 `ea0bd8ba3094` 置为 cancelled；没有派发执行器。浏览器编辑 Prompt 后打开该历史任务，快照仍为固定时的 `M6 edited: {text}`，当前资源为 `M6 after freeze: {text}`，后端内容哈希复核一致。 |
| 旧流程与历史 | 打开原 SFT2000 配置与旧 13 步配置；打开旧完成任务 `8273f63acb84` 的详情。原有 Pipeline 和任务记录逐条比对保持一致。 |

文本新 PDF 到配置、离线训练产物到发布是分别验证的两段通路。离线任务来自先前实际 PandasOperator 转存固定样本，不是新上传 PDF 的生成结果，也不是本轮执行了真实 13 步。资源快照记录为“仅固定，未调度”，状态为已取消、进度 0/1；不能将其计为生成成功。

浏览器截图保存在忽略目录 `output/playwright/`：`m6-wizard-roundtrip.png`、`m6-task-collect.png`、`m6-published.png`、`m6-mm-reopened-blocked.png`、`m6-resource-history.png`、`m6-legacy-open.png`。发布页面截图已实际检查布局。浏览器状态文本位于 `outputs/platform-m6-*.txt`；下载核对为 `outputs/platform-m6-download-verification.json`、`outputs/platform-m6-metadata-verification.json`。校验脚本 `outputs/platform-m6-verify.py` 以工作区 `.venvs/dataflow/bin/python` 执行。测试浏览器会话已关闭，保留原 WebUI 服务。

## 数据保留和 Git 边界

实施前将现有 33 份 JSON 及逐文件 SHA-256 清单保存到 `outputs/backups/platform-m6/`，本轮再次核对备份哈希全部匹配。它是本轮涉及 JSON 的验收前备份，不是整个运行环境或全部媒体的灾备副本。最终比对：

- 原有 36 条 Pipeline 逐条完全相同，新增 1 条明确标注的未运行配置。
- 原有 19 条任务逐条完全相同，仅新增 1 条立即取消、未调度的资源快照验收记录。无新完成任务、无真实模型请求。
- 原有草稿、发布版本、材料元数据、Schema、偏好与缓存 JSON 字节未变。备份中的 33 份文件没有缺失，只有 Pipeline / 任务 / MM 配置 / 用户 Prompt 的四份集合文件变化，其旧记录保留。
- 新增专用 PDF 材料及输入清单、一份文本草稿及 v1、一个 MM 配置和一个用户 Prompt，便于界面复查。新文本草稿保留发布后的编辑，展示旧版本稳定性；没有覆盖旧实验数据。

本轮源码范围只有 WebUI 文档与工作区 README、计划及本记录。核心、MM、PDF 扩展代码未修改；没有为未修改仓库制造提交。工作区原有 `pipelines/SFT-PIPELINE-OPERATORS.md` 删除继续保持未提交。

## 仍然待验的外部运行条件

真实文本小 PDF 需在文本端点、凭据、解析环境与执行授权具备时单独试跑；本轮没有用历史成功或离线样本宣称端点当前可用。真实视觉调用及独立 MM 执行桥接未实现/未验收，配置中的服务引用不会解除拦截。没有下载模型、部署 GPU 或安装 MM 全量依赖。训练、DPO、多用户共享部署、质量专项评估和细粒度恢复继续在当前范围之外。
