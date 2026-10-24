# 首批目录迁移回执

本批实际迁移 Mac 五个目录和学校最新八组结果。旧入口相对链接兼容；学校统一入口是链接，实体仍在原容器挂载范围内。

- `mac-migration-result.json`：五项目录、文件数、字节数及原清单 SHA-256。
- `school-migration-result.json`：学校新实体、统一入口、旧入口及校验计数。
- `school-container-path-check.json`：断网、禁用 GPU、只读挂载的容器路径与文件验证；原五个容器配置和状态不变。
- `navigation-updates.json`：唯一在迁移后修改的原导航 README 前后哈希；原始截图、模型、响应和证据未改写。
- `school-navigation-update.json`：学校根目录、运行和环境导航更新的前后哈希。
- `reference-validation.json`：原先有效的 110 处本机路径继续可读，完整文件清单复核和文档链接检查的结果。
- `container-resource-snapshot.json`：用户后续询问的五个容器资源快照；没有执行容器删除。
- `audit-manifest.json`：本目录内容、执行脚本、本地完整清单和回归日志哈希。

完整清单保留在 Mac `outputs/maintenance/2026-10-24-directory-migration/`；学校清单在 `runs/maintenance/2026-10-24-directory-migration/`。迁移脚本为本次冻结批次的审计源文件，已有回执时拒绝重复执行；不是通用批量改名命令。

详细范围见 [迁移报告](../../../../docs/maintenance/workspace-migration-stage1-20261024.md)。
