# DataFlow 工作区基线

本目录管理本项目的脚本、Pipeline 配置、文档、依赖清单和 `paper-dataflow` 扩展。`repos/dataflow` 与 `repos/dataflow-webui` 是两个独立 Git 仓库，不嵌入本仓库；各自的修复保存在 `Mau-Q` fork 的分支中。

| 目录 | 当前分支 | 基线提交 | 远端 |
| --- | --- | --- | --- |
| `repos/dataflow` | `local/reusable-sft-operator-fixes` | `0d08eb357a633b92543d8fa5b73b94a2c2830541` | `Mau-Q/DataFlow` |
| `repos/dataflow-webui` | `local/reusable-sft-webui-fixes` | `a12118c749118c26e30edce43badc61eb4667b4f` | `Mau-Q/DataFlow-WebUI` |

WebUI 的 `a12118c` 是本机集成改动的独立本地提交；此前的 `06a5a0a` 已推送至 fork。根目录基线也只在本机提交，不代表这三个仓库已有同一发布版本。

## 纳入与排除

- 跟踪：项目脚本、Pipeline 配置与执行说明、扩展源码、安装与依赖清单。
- 不跟踪：两个嵌套仓库、虚拟环境、模型、原始数据、运行缓存、输出、日志、密钥、本机 Codex 配置和历史补丁。排除规则见 `.gitignore`。
- `pipelines/` 中的部分注册记录含本机绝对路径与任务 ID，是本地运行快照；克隆到其他机器后必须重新绑定输入、Serving 和输出路径。
- `data/`、`logs/`、`outputs/` 未纳入 Git。Git 提交不能单独复现历史实验结果；对应原始材料与运行证据应另行归档。

## 开发检查

修改前后分别执行 `git status --short --branch`，在本目录和两个 `repos/` 仓库各检查一次。提交时按仓库分别暂存目标文件、检查暂存 diff；不要从本目录运行 `git add -A` 来代替对三个仓库的检查。

本机运行使用 editable 安装的 DataFlow，修改源码后应确认 WebUI/Ray 进程加载了目标版本。`repos/dataflow-webui/backend/app/core/config.py` 当前启用 `paper_dataflow`，新环境需先安装 `extensions/paper-dataflow`。
