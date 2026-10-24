# 工作区与公开源码基线

2026-10-22：Core、WebUI、DataFlex 改为总仓库中的普通源码目录，不再依赖独立 fork 或外部 DataFlex 路径。原目录位置保持不变，DataFlex 放在 `repos/dataflex`；可选 MM 保留子模块。

导入来源由 [locks/components.json](locks/components.json) 及各源码目录的 `UPSTREAM.json` 记录。来源记录保存导入提交与原始文件哈希，后续修改统一由总仓库 Git 历史管理。`python3 scripts/check-workspace.py` 检查源码存在、来源一致性、普通文件跟踪及可选子模块版本。

此次本机迁移前的 Core / WebUI Git 元数据保存在 `.git/component-history/2026-10-22/`，包含原有提交和 stash，不上传 GitHub。独立 `/Users/rui/Documents/DataFlex` 未删除。历史基线与旧交付记录仅说明当时结构。

## 跟踪边界

- 跟踪：源码、文档、脚本、配置模板、合成测试材料和组件版本。
- 排除：环境、模型、日志、缓存、原始材料、运行输出、数据库、密钥及本机编辑器/Agent 配置。
- 旧 `pipelines/*.registration.json`、论文实验脚本和环境冻结文件保留历史用途，可能包含本机路径与任务 ID，不能直接当作可移植配置。当前使用入口见 [README](README.md)。

## 提交与验证

先检查总仓库 Git 状态，集成源码统一在总仓库提交。不要使用全仓 `git add -A` 顺带提交其他任务的改动。

完整本地回归运行 `./scripts/test-local.sh`，前端另执行 Node 契约测试与构建。安装与端口可访问不证明模型/API、MinerU 或 MM 的真实运行能力。

历史安装记录已移至 [docs/archive](docs/archive/INSTALLATION_STATUS.md)；阶段交付见 [文档索引](docs/README.md)。

## 目录与命名维护

Mac/学校的目录职责、新运行命名和迁移状态见 [目录约定](docs/workspace-layout.md)。2026-10-24 的检查阶段先补文档，随后按用户授权完成 [首批实体迁移](docs/maintenance/workspace-migration-stage1-20261024.md)。`output/` 等旧入口以相对符号链接兼容，新任务统一使用按用途分组的 `outputs/`；模型、环境、数据库、应用默认运行路径和容器挂载保持原状。
