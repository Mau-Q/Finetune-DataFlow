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
