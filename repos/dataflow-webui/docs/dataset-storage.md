# 数据集 SQLite 存储、备份与恢复

2026-10-19 后续实施。用户在 M1–M6 文件持久化交付后，明确授权统一数据库，同时补齐受管 PDF 副本、持久化和自动备份恢复。

## 权威数据与文件

`backend/data/datasets.sqlite3` 是原始数据集、材料、生成草稿、样本、媒体关联、导入记录和发布版本元数据的唯一权威。当前 schema version 为 2。

- `source_datasets`：保留旧数据集 ID、名称、输入位置与其他注册信息。
- `source_members`：文件清单成员、顺序、文件位置与材料 ID 关联。
- `materials`：PDF / 图片的元数据、来源和 SHA-256。
- `drafts`、`samples`：草稿属性、样本顺序、样本标识和样本内容。
- `draft_media`、`draft_imports`：显式媒体绑定与导入记录。
- `releases`：不可变发布版本的元数据与文件校验信息。

文件格式、内容分类、输入模态和训练类型分别表达。PDF、PNG、CSV 等文件继续保存在文件系统；公式与表格仍可通过原文件或解析产物管理。本次没有新增公式/表格专用编辑器，也没有新增模型生成流程。

文件写入使用同目录临时文件、fsync、原子替换和目录同步；数据库使用事务、外键、WAL、FULL synchronous。样本和媒体关联在同一事务提交，跨进程数据集写入和备份共用文件锁。文件已落盘但数据库事务未提交时，可能留下未被引用的新文件；不会把半条元数据作为成功数据集展示。

单样本编辑直接更新对应 `samples` 行；批量写入按记录差异更新样本、媒体和导入关系。草稿列表通过 SQL 统计行数和字段，分页只读取所请求的样本。跨线程、跨进程协调统一保留根目录 `dataset_lock` 与 SQLite 事务，移除额外的 library 私有锁。

旧 `data_registry.yaml` 与 `library/{materials,drafts,releases}/*.json` 只作为一次性迁移输入，保留原文件，不再作为第二套实时数据库。迁移后编辑这些旧文件不会改写数据库。Prompt、Schema、Pipeline、任务等其他服务保留现有存储方式，本次没有迁移整个 WebUI 的全部状态。

## 论文副本

旧 13 篇论文数据集 ID `a5f3dd5c5d` 保持不变。PDF 已复制到 `library/materials/`，当前清单位于 `library/inputs/adopted-a5f3dd5c5d.jsonl`；文件成员关联也已进入数据库。原 PDF 和原清单均保留。接管逐份比对 SHA-256，不以同名文件猜测对应关系。

## 自动备份

默认目录为 `backend/backups/datasets/`，可用 `DATAFLOW_DATASET_BACKUP_DIR` 为服务指定另一个位于数据目录外的本地路径；管理命令同时通过 `--backup-dir` 指定相同目录（放在子命令前）。

- 服务启动时备份；服务运行期间每小时备份。
- 材料、原始数据集、草稿和发布版本成功修改后只标记待备份；后台线程约 1 秒合并同一批修改后生成快照，关闭服务时补齐待备份修改。数据库事务本身仍同步持久化，前台请求不再压缩备份。
- SQLite 通过备份 API 生成一致性镜像，包含已提交 WAL 页面；不直接复制打开的主库或 WAL。
- 备份包含 `library/` 数据文件、旧数据集注册表、数据库镜像、注册表引用的数据文件，以及可读取的 PDF/图片依赖。未被数据集引用的 Core 运行模板、任务历史与模型服务配置不纳入数据集快照；恢复时保留当前这些文件，旧快照仍可验证与恢复。
- 每个备份包含逐文件大小与 SHA-256 清单，发布前校验。源文件在备份期间变化则该次失败，保留已有备份。
- 保留最近 24 份自动/手动快照，迁移前 baseline 单独保留。备份目录权限为 700、归档为 600；历史快照可能含本地服务配置，所有快照均不能提交到 Git。
- `/api/v1/library/storage/status` 提供数据库计数、备份线程状态、最近快照和最近错误。备份失败会记录错误；已提交数据仍保存在主库，不能把备份失败当作成功保护。

这属于本地备份，不是异地备份；同一磁盘整体损坏仍需另外保存的副本。服务关闭时定时线程不运行；恢复服务后会立即备份。

## 管理命令

在 WebUI 仓库下，用实际后端 Python 环境执行：

```sh
/path/to/backend-python scripts/datasets.py status
/path/to/backend-python scripts/datasets.py backup
/path/to/backend-python scripts/datasets.py verify /absolute/snapshot.zip
/path/to/backend-python scripts/datasets.py restore /absolute/snapshot.zip --target /new/empty-path
```

`restore` 仅写入一个尚不存在的新目录。其 `data/`、`external/` 和 `manifest.json` 保留精确字节，可用于隔离核验和人工检查。校验会把绝对路径解析到恢复副本，而非误读仍存在的线上原件。隔离副本不自动改写历史任务中的绝对路径与内容哈希，不宣称跨机器直接启动。

## 启动恢复与指定版本回退

启动服务前会检查数据库完整性、外键、材料哈希、样本媒体关联、注册文件与已发布文件。数据库缺失/损坏或受管文件缺失/损坏时，从最近有效的 SQLite 快照恢复；先完整验证恢复副本，再将受损目录另存 `quarantine-*`，不删除受损现场。没有有效 SQLite 备份则明确失败，不创建空库冒充恢复。

手动原地恢复前停止 API 和所有执行 worker。管理命令检测到本地服务端口仍监听时会拒绝：

```sh
/path/to/backend-python scripts/datasets.py recover
/path/to/backend-python scripts/datasets.py recover --archive /absolute/selected-snapshot.zip
```

不指定版本时仅修复损坏状态；指定快照可回退一次已提交的误删，当前数据也会保留到 quarantine。恢复不会覆盖备份后已经变化的外部原文件；遇到这种情况保留现场并要求人工核对。恢复原目录后，旧绝对路径继续有效；跨目录迁移需另行重映射。

历史清单中在本次迁移前已经失效的外部路径会记录在备份清单 `unresolved_external` 中，原记录原样保留，不假装已补回。当前发现一条旧 LIMA 实验的 Downloads 路径；可见的 13 篇论文数据集已全部转为有效受管副本，不依赖该旧路径。

## 验证

测试覆盖：旧文件只导入一次、ID 与内容保留、事务回滚、并发更新、进程在事务中退出、论文副本与原件哈希、备份后原件不可用的隔离恢复、数据库损坏/缺失和图片损坏的自动恢复、受损现场保留、篡改备份拒绝、外部原件变化拒绝覆盖、定时与合并修改备份、轮转及指定快照撤销误删。
