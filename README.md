# Finetune-DataFlow

基于 [OpenDCAI DataFlow](https://github.com/OpenDCAI/DataFlow) 与 [DataFlow-WebUI](https://github.com/OpenDCAI/DataFlow-WebUI) 的本地微调数据生成平台。通过可视化 Pipeline，将文本或图片材料转换成 SFT / DPO 训练样本，并管理来源、运行记录、数据集草稿和发布版本。

支持个人在本机使用，以及管理员维护的局域网小团队共享；默认仅监听 `127.0.0.1`。团队模式采用独立账号、项目隔离、单人人工评测和固定导出，不提供产品内 Agent/MCP 入口。已在 macOS Apple Silicon 和 Windows 11 验证本地开发；Windows 实测安装、原生选择器、浏览器交互与无需模型的 CPU 流程，详见 [实机验收](docs/windows-acceptance.md)。这不代表所有算子、模型与硬件均可用。

## 能做什么

- 导入原始文本、PDF、图片，管理生成数据集、样本和媒体关联。
- 在原生画布编辑流程、字段绑定、Prompt、JSON Schema 和模型服务。
- 使用四类代表流程生成文本 SFT、文本 DPO、图文 SFT、图文 DPO。
- 运行前选择新建数据集或追加到已有数据集；成功的有效结果自动收录。
- 逐条隔离无效样本，保留 `invalid_samples.jsonl`；相同 DPO 回答最多额外生成负例 2 次。
- 保存任务输入与资源快照，查看步骤、模型响应、产物，导出 JSONL 或含图片的 ZIP。
- 使用 SQLite 保存数据集元数据，并提供备份、恢复和版本化发布。
- 查看来源的生成情况，创建固定评测批次，领取、评分、修订并通过。
- 从草稿或发布版本导出 JSONL、Alpaca、对话、DPO 与图文 ZIP，并单独导出评测明细。

当前代表流程不调用模型评分。DPO 使用合成正例和负例，`chosen/rejected` 来自生成角色，仍需对照来源人工核验。代码检查、任务成功和结构合规均不代表数据质量或训练收益得到证明。

局域网团队部署请使用 [团队使用与 HTTPS 配置](docs/lan-usage.md)。完整规格和本轮验证见 [Spec](docs/lan-collaboration-data-review-spec.md) 与 [实施验收记录](docs/lan-implementation.md)。

## 快速开始

需要 Git、[uv](https://docs.astral.sh/uv/)、Node.js 22 和 npm。安装会下载 Python 3.12 与依赖；不需要下载本地大模型。已有工作环境可直接使用启动命令，无需重复安装。

```sh
git clone https://github.com/Mau-Q/Finetune-DataFlow.git
cd Finetune-DataFlow
./scripts/setup.sh
./scripts/webui.sh --daemon
./scripts/webui.sh --status
```

打开 [本地 WebUI](http://127.0.0.1:8001/)，开发模式自动进入本机默认工作区。停止服务：`./scripts/webui.sh --stop`。
Windows 首次安装，在 PowerShell 中执行（Core、WebUI、DataFlex 源码已包含在仓库中，不安装可选 MM）：

```powershell
git clone https://github.com/Mau-Q/Finetune-DataFlow.git
Set-Location Finetune-DataFlow
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\setup-windows.ps1
.\scripts\webui-windows.ps1 -Action Foreground
```

各开发者分别运行本机实例，互不共享账号、数据库、密钥和虚拟环境。Windows 使用根目录 `.venv`，默认以“本地开发者”进入“默认工作区”；退出后刷新停留登录页，“进入本地工作区”可恢复。普通登录使用 `-RequireLogin`，LAN 入口默认不开启开发自动登录。日常只需执行最后一条启动命令，停止前台服务按 Ctrl+C。详细步骤见 [Windows 开发指南](docs/windows-development.md)。

DataFlex 固定使用 `repos/dataflex`，不读取 `DATAFLEX_SOURCE_DIR`。导出训练运行包会携带源码；训练主机仍需准备训练依赖和模型，WebUI 安装不会安装 GPU 训练环境。

安装细节、常见问题和可选 PDF 解析见 [安装与启动](docs/getting-started.md)。

首次生成：在 WebUI 配置模型服务 → 导入示例 → 选择模板并为每个模型节点绑定服务 → Save & Run → 选择收录目标和输出目录 → 检查结果。API 配置及真实运行由使用者在自己的实例完成。

| 模板 | 输入 | 输出字段 | 常规模型节点数 |
| --- | --- | --- | ---: |
| 文本 SFT | JSONL 的 `text` | `instruction/input/output` | 1 |
| 文本 DPO | JSONL 的 `text` | `prompt/chosen/rejected` | 2 |
| 图文 SFT | 导入的图片材料 | `messages/images` | 2 |
| 图文 DPO | 导入的图片材料 | `prompt/chosen/rejected/images` | 3 |

DPO 配对节点另有负例重试服务绑定，通常复用生成服务。详见 [模型 API 配置](docs/model-api.md) 和 [示例与核对方法](repos/dataflow-webui/examples/representative-training/README.md)。

## 仓库结构

```text
repos/
  dataflow/          # Core 源码，由总仓库统一管理
  dataflow-webui/    # WebUI 源码，由总仓库统一管理
  dataflex/          # DataFlex 训练引擎源码，随运行包分发
  dataflow-mm/       # 可选上游参考，独立 Python 环境
extensions/
  paper-dataflow/    # 论文解析衔接、分块及 QA 扩展
scripts/             # 安装、启动、检查、回归和历史实验工具
pipelines/           # 论文流程配置及历史实验记录
locks/               # 组件提交与本机环境快照
  components.json    # 集成源码来源及可选子模块版本
docs/                # 安装、API、架构、开发及历史交付记录
deploy/              # 部署入口、固定方案与紧凑验收证据
tools/               # 个人 API 执行器等独立工具
```

Core、WebUI 和 DataFlex 直接纳入本仓库，普通 `git clone` 即包含源码，无需单独克隆 fork 或配置 DataFlex 路径。各目录保留上游许可证及 `UPSTREAM.json` 来源快照；后续修改统一在本仓库提交。只有可选 MM 仍为子模块。环境、模型、原始数据、密钥、SQLite 数据库、缓存和生成输出都不纳入 Git。旧论文实验配置含本机路径，须重新绑定后使用；历史依赖快照不能直接作为跨平台安装清单。

## 文档与验证

- [文档索引](docs/README.md)：区分当前指南与历史交付。
- [架构与组件边界](docs/architecture.md)：向导、画布、任务、数据集和 MM 隔离。
- [开发与验证](docs/development.md)：版本更新、提交和离线测试。
- [组件与工作区基线](WORKSPACE_BASELINE.md)：当前固定源码和保留的本地状态。
- [目录职责与命名](docs/workspace-layout.md)：两端运行数据、环境、历史输出和迁移规则。
- [学校部署与操作](docs/school-server-deployment.md)：学校目录、平台状态卷和解析/训练入口。
- [上游与许可](THIRD_PARTY.md)：来源及再分发边界。

```sh
python3 scripts/check-workspace.py
./scripts/test-local.sh
cd repos/dataflow-webui/frontend
node --test src/hooks/dataflow/*.test.mjs
npm run build
```

Unix 完整本地回归使用 `.venvs/dataflow`；Windows 等效入口为 `.\scripts\test-local.ps1`，使用 `.venv` 并启用 UTF-8。两者排除 Core 的 `gpu` 标记；缺少历史论文 tokenizer / 回放数据时对应测试明确跳过。CI 检查组件、前端、Windows 持久化和脚本等；真实模型兼容性、内容质量和可选 MinerU / DataFlow-MM 执行需要另外验收。

## 许可

本仓库使用 [Apache-2.0](LICENSE)。各集成组件、可选子模块及引用代码以其各自许可证为准，详见 [THIRD_PARTY.md](THIRD_PARTY.md)。
