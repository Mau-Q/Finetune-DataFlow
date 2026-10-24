# 2026-10-24 首批目录迁移与兼容验证

用户授权按已审阅的命名方案迁移历史 UI 验收和已结束的运行目录，保留旧路径，校验文件与引用，更新文档并提交推送。本次实际完成 Mac 五项和学校一项；没有删除运行内容或重跑商业调用、解析生产及 GPU 训练。

## 已完成的实体迁移

Mac 根目录为 `/Users/rui/Documents/DataFlow`。下表的旧路径均保留为指向新实体的**相对符号链接**，不在 Git 中跟踪运行数据或这些链接。

| 旧路径 | 新实体路径 | 原有普通文件数 |
| --- | --- | ---: |
| `output/` | `outputs/archive/ui/legacy-output/` | 413 |
| `outputs/dataflex-core8-20261023/` | `outputs/dataflex/2026-10-23-core8-initial-protocol/` | 25 |
| `outputs/dataflex-strategy-school-audit-20261023/` | `outputs/dataflex/2026-10-23-school-source-audit/` | 28 |
| `outputs/qwen35-9b-8192-env-audit/` | `outputs/environment-checks/2026-10-22-qwen35-9b/` | 949 |
| `outputs/closeout-20261024/` | `outputs/maintenance/2026-10-24-dataflex-closeout/` | 13 |

同一文件系统内重命名，随后建立兼容链接。迁移前后核对 1,428 个普通文件，共 59,960,095 字节；文件 SHA-256、大小、模式、目录条目及符号链接原文均保持一致。

迁移后单独更新了 UI 目录的 README：原相对文档链接依赖旧层级，现改为同时适用于旧入口和新实体的绝对本机链接。该导航文件的前后哈希单独记录，其他原始文件不改写。另在新分类目录外层补充 README，不向冻结结果内部插入新文件。

## 学校的实体与统一入口

共享根目录为 `/sharedata/home/huruiqian/DataFlow`。

- 旧入口：`runs/qwen35-9b/20261022-smoke/strategy-20261023/gpu1-core8-20261024/`。
- 新实体：`runs/qwen35-9b/20261022-smoke/dataflex/2026-10-24-core8-flow-check/`。
- 统一入口：`runs/dataflex/2026-10-24-core8-flow-check/`。

旧入口与统一入口都是指向新实体的相对符号链接。新实体仍处于保留训练容器原来的挂载范围内，因此无需重建容器或修改原始 YAML。

容器内对应关系：

```text
/runs/strategy-20261023/gpu1-core8-20261024  # 旧兼容入口
    -> /runs/dataflex/2026-10-24-core8-flow-check  # 新实体
```

这里的 `/runs` 对应宿主的旧 smoke 根；不能误认为它等于宿主整个 `runs/`。统一入口是宿主导航入口，新实体位置由清单明确记录，没有把入口链接标成实体目录。

学校 619 个普通文件、1,590,698,639 字节逐项校验一致。G00—G07 最终 adapter、预测、日志和状态记录保留。三处指向共享数据/门测/数据清单的原符号链接文本保持不变。

## 引用与运行边界验证

- 扫描总仓库中与所迁目录相关的路径文字及 Markdown 链接，原先存在的 110 处路径在迁移后仍可访问。另有 16 个迁移前已不对应本机文件的词法候选，主要是服务端相对路径、代码表达式和历史已清理文件；未将它们算成有效引用或本轮新增断链。
- 检查搬迁目录内 Markdown 的相对链接，发现并单独修复一处可变导航 README 链接。没有批量替换历史 JSON、运行配置或证据中的旧路径。
- 使用已有训练镜像启动一次性校验容器，禁用 GPU、断网并只读挂载同一个 smoke 根；核对容器内旧、新路径、全部 619 个文件和三处冻结链接。没有加载模型或运行训练。校验容器随后自动移除。
- 核对原有五个容器 ID、镜像、状态和完整挂载配置保持一致：平台与 HTTPS 运行，三个训练容器停止。
- 迁移后执行 `./scripts/test-local.sh`：Core CPU 165 通过、1 deselected；WebUI 后端 491 通过、另有 7 个 subtests 通过；论文扩展 54 通过。合计 710 项通过。此结果验证相关本地回归，不替代训练或商业 API 验证。

原始哈希清单继续保留生成时的路径。通过旧链接仍能定位保留文件；此前收尾中已主动删除的大权重仍以原删除回执解释，不能把目录迁移视为恢复这些权重。

## 暂未迁移的内容

`paper-batch-20261022` 及其学校批处理工作目录有暂停、待复核或未完成部分，本批不移动。MinerU 作业目录仍有 root/owner 和 worker 路径依赖，另批处理。应用业务数据、数据库、缓存、基座模型、Python 环境、Docker 镜像和状态卷保持原位。

## 证据与后续使用

紧凑回执见 [stage1-evidence](../../deploy/plans/workspace-layout-20261024/stage1-evidence/README.md)，当前条目状态见 [rename-plan.json](../../deploy/plans/workspace-layout-20261024/rename-plan.json)。

完整迁移前清单、参考路径基线、README 原文及本地回归日志保存在 Mac 的 `outputs/maintenance/2026-10-24-directory-migration/`；学校完整清单在 `runs/maintenance/2026-10-24-directory-migration/`。两个清单均在被迁移目录之外。

以后浏览已结束结果优先使用新入口；旧入口用于兼容历史报告和代码。不要只删除旧链接、覆盖同名目标或将它们当成第二份占用空间的数据。后续若改变容器挂载，应另行核对旧、新两个容器路径，不能只根据宿主路径判断兼容性。
