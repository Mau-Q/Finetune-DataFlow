# 数据集 SQLite、受管副本与备份恢复交付

日期：2026-10-19。范围依据用户在原 M1–M6 交付后的追加授权，见 [ADR 0006](adr/0006-unified-dataset-sqlite-and-recovery.md)。

WebUI 源码提交：`1a40b3e`（SQLite 与备份恢复）、`f1eda93`（受管路径重新登记时保持原 ID）。

## 完成内容

- SQLite 统一管理原始数据集、文件成员、材料、生成草稿、样本、媒体绑定、导入记录与发布元数据。数据库为 WebUI 的 `backend/data/datasets.sqlite3`，schema version 2。旧 YAML/JSON 保留为一次性迁移来源，不作为另一套实时权威。
- 原始数据集 `a5f3dd5c5d` 的 13 篇 PDF 保存平台副本；保留原 PDF、原清单及数据集 ID。当前清单为 `backend/data/library/inputs/adopted-a5f3dd5c5d.jsonl`，数据库也保存成员与材料 ID 关联。
- 数据库事务、外键、WAL、FULL synchronous；文件临时写入、fsync、原子替换和目录同步。批量材料导入共用事务。
- 服务启动、成功修改及运行期间每小时自动备份；最近 24 份快照轮转，迁移前 baseline 单独保留。SQLite 使用备份 API，避免复制打开的主库或 WAL。
- 启动时损坏恢复、选择快照回退、空目标隔离恢复、逐文件哈希验证；受损现场另存 quarantine，外部原件变化时拒绝覆盖。数据库缺失时拒绝创建空备份。
- 状态 API：`GET /api/v1/library/storage/status`。管理命令及恢复边界见 [操作说明](../repos/dataflow-webui/docs/dataset-storage.md)。

## 线上迁移核对

| 对象 | 结果 |
| --- | --- |
| 原始数据集 | 74 条 ID 全保留；除目标论文数据集的受管路径更新外，其余 73 条内容一致 |
| 材料 | 原有 5 条内容一致；新增 13 份论文副本，共 18 条 |
| 生成草稿与样本 | 原有 8 个草稿、12 条样本保留，包含隐藏记录；界面可见 5 个草稿 |
| 发布版本 | 3 个既有版本的元数据及下载文件哈希保持一致 |
| 论文原件 | 13 份逐文件 SHA-256 与迁移前备份一致，未移动或删除 |
| 数据库关系 | 17 条原始文件成员关系、4 条草稿媒体绑定；完整性与外键校验通过 |
| 真备份恢复 | 在新隔离目录恢复 211 个文件，逐文件 SHA-256 一致；数据库及受管媒体、发布文件校验通过 |

运行证据保存在本地私有目录 `repos/dataflow-webui/backend/backups/datasets/`：

- `baseline-evidence.json`：迁移前清点及快照。
- `adoption-a5f3dd5c5d.json`：逐份论文原件、副本与哈希。
- `migration-verification.json`：ID、记录内容、原件与隔离恢复核验结果。
- `verified-isolated-restore/`：真实备份的隔离恢复副本。

上述运行数据、数据库及备份不提交 Git。

## 测试与浏览器

- 完整 `./scripts/test-local.sh` 通过：核心 158 项（1 项 deselected）、WebUI 233 项及 7 个子测试、PDF 扩展 30 项。
- 补充空备份拒绝及 WAL 备份覆盖测试后，最终 WebUI 后端全量 235 项及 7 个子测试通过。
- 存储专项 15 项覆盖：旧文件迁移不重复、ID 和内容保留、事务失败回滚、并发更新、事务中进程退出、论文接管幂等及原件保留、离线原件不可用的隔离恢复、数据库损坏/缺失与图片损坏恢复、现场保留、篡改备份拒绝、变化的外部文件保护、定时/修改后备份、轮转、指定版本撤销误删、丢库时拒绝空备份、WAL 已提交页面纳入备份。
- 浏览器复核原始列表、论文详情及刷新、生成列表、图文 DPO 图片和旧 SFT 版本下载入口。首篇和末篇论文的文件 API 返回字节与平台副本一致。未发起模型任务。
- 最终状态 API 显示自动备份线程启用，最近错误为空。测试浏览器已关闭。

## 明确边界

旧 LIMA 实验清单原先已有一条失效的外部路径 `/Users/rui/Downloads/SFT-data-composition-reading/02_Zhou_2023_LIMA_Less_Is_More_for_Alignment.pdf`。原记录保留，并记入备份的 `unresolved_external`；没有凭同名文件猜测修复，也没有将此项声称为可恢复的旧原件。可见的 13 篇论文数据集已经完全使用有效的受管副本。

自动恢复在启动时执行，定时备份只在服务运行期间执行。本地备份不覆盖整盘损坏；跨机器恢复需核对绝对路径。本次未迁移整个 WebUI 的 Prompt、Schema、Pipeline、任务等其他状态，也不备份所有未登记运行缓存。

工作区原有 `pipelines/SFT-PIPELINE-OPERATORS.md` 删除保持未提交。
