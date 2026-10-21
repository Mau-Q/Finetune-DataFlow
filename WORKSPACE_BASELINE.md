# 工作区与公开源码基线

2026-10-20：统一公开入口为 `Mau-Q/Finetune-DataFlow`。根仓库管理集成脚本、文档、Pipeline、依赖记录及论文扩展；三个组件以固定提交的 Git 子模块引用，各自保留独立历史。下表已于 2026-10-21 同步至 Windows/review 修复与 DataFlex 整合后的版本。

| 目录 | 固定提交 | 远端 |
| --- | --- | --- |
| `repos/dataflow` | `b5b69c144617abf24005bb61db5ab7e2cef865e7` | https://github.com/Mau-Q/DataFlow.git |
| `repos/dataflow-webui` | `566ff32e1cd35c640b161fd2f1b5dae9ae3412db` | https://github.com/Mau-Q/DataFlow-WebUI.git |
| `repos/dataflow-mm` | `155253460f6f2e50705a3e779f259b382a382822` | https://github.com/OpenDCAI/DataFlow-MM.git |

权威版本清单为 [locks/components.json](locks/components.json)，`python3 scripts/check-workspace.py` 检查清单、gitlink、当前 checkout 与 URL 是否一致。安装不会重置现有开发 checkout。

## 跟踪边界

- 跟踪：源码、文档、脚本、配置模板、合成测试材料和组件版本。
- 排除：环境、模型、日志、缓存、原始材料、运行输出、数据库、密钥及本机编辑器/Agent 配置。
- 旧 `pipelines/*.registration.json`、论文实验脚本和环境冻结文件保留历史用途，可能包含本机路径与任务 ID，不能直接当作可移植配置。当前使用入口见 [README](README.md)。

## 提交与验证

先检查涉及仓库的 Git 状态，各仓库分别提交，推送组件提交后再发布根仓库引用。不要使用全仓 `git add -A` 顺带提交其他任务的改动。

完整本地回归运行 `./scripts/test-local.sh`，前端另执行 Node 契约测试与构建。安装与端口可访问不证明模型/API、MinerU 或 MM 的真实运行能力。

历史安装记录已移至 [docs/archive](docs/archive/INSTALLATION_STATUS.md)；阶段交付见 [文档索引](docs/README.md)。
