# Finetune-DataFlow

基于 [OpenDCAI DataFlow](https://github.com/OpenDCAI/DataFlow) 与 [DataFlow-WebUI](https://github.com/OpenDCAI/DataFlow-WebUI) 的本地微调数据生成平台。通过可视化 Pipeline，将文本或图片材料转换成 SFT / DPO 训练样本，并管理来源、运行记录、数据集草稿和发布版本。

面向个人在本机独立使用，默认仅监听 `127.0.0.1`。当前主要验证环境是 macOS Apple Silicon；Linux / Windows 尚未完成同等本地验收。

## 能做什么

- 导入原始文本、PDF、图片，管理生成数据集、样本和媒体关联。
- 在原生画布编辑流程、字段绑定、Prompt、JSON Schema 和模型服务。
- 使用四类代表流程生成文本 SFT、文本 DPO、图文 SFT、图文 DPO。
- 运行前选择新建数据集或追加到已有数据集；成功的有效结果自动收录。
- 逐条隔离无效样本，保留 `invalid_samples.jsonl`；相同 DPO 回答最多额外生成负例 2 次。
- 保存任务输入与资源快照，查看步骤、模型响应、产物，导出 JSONL 或含图片的 ZIP。
- 使用 SQLite 保存数据集元数据，并提供备份、恢复和版本化发布。

当前代表流程不调用模型评分。DPO 使用合成正例和负例，`chosen/rejected` 来自生成角色，仍需对照来源人工核验。代码检查、任务成功和结构合规均不代表数据质量或训练收益得到证明。

## 快速开始

需要 Git、[uv](https://docs.astral.sh/uv/)、Node.js 22 和 npm。安装会下载 Python 3.12 与依赖；不需要下载本地大模型。已有工作环境可直接使用启动命令，无需重复安装。

```sh
git clone --recurse-submodules https://github.com/Mau-Q/Finetune-DataFlow.git
cd Finetune-DataFlow
./scripts/setup.sh
./scripts/webui.sh --daemon
./scripts/webui.sh --status
```

打开 [本地 WebUI](http://127.0.0.1:8000/)。停止服务：`./scripts/webui.sh --stop`。
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
  dataflow/          # Core fork，固定提交的子模块
  dataflow-webui/    # WebUI fork，固定提交的子模块
  dataflow-mm/       # 可选上游参考，独立 Python 环境
extensions/
  paper-dataflow/    # 论文解析衔接、分块及 QA 扩展
scripts/             # 安装、启动、检查、回归和历史实验工具
pipelines/           # 论文流程配置及历史实验记录
locks/               # 组件提交与本机环境快照
  components.json    # 当前源码版本的权威清单
docs/                # 安装、API、架构、开发及历史交付记录
```

组件采用子模块，保留上游许可证与独立 Git 历史。环境、模型、原始数据、密钥、SQLite 数据库、缓存和生成输出都不纳入 Git。旧论文实验配置含本机路径，须重新绑定后使用；历史依赖快照不能直接作为跨平台安装清单。

## 文档与验证

- [文档索引](docs/README.md)：区分当前指南与历史交付。
- [架构与组件边界](docs/architecture.md)：向导、画布、任务、数据集和 MM 隔离。
- [开发与验证](docs/development.md)：版本更新、提交和离线测试。
- [组件与工作区基线](WORKSPACE_BASELINE.md)：当前固定源码和保留的本地状态。
- [上游与许可](THIRD_PARTY.md)：来源及再分发边界。

```sh
python3 scripts/check-workspace.py
./scripts/test-local.sh
cd repos/dataflow-webui/frontend
node --test src/hooks/dataflow/*.test.mjs
npm run build
```

完整本地回归使用 `.venvs/dataflow`，排除 Core 的 `gpu` 标记测试。CI 检查组件版本、仓库边界、前端契约和构建；完整 Python 回归在本机运行。真实模型兼容性、内容质量和可选 MinerU / DataFlow-MM 执行需要另外验收。

## 许可

本仓库使用 [Apache-2.0](LICENSE)。各子模块及引用代码以其各自许可证为准，详见 [THIRD_PARTY.md](THIRD_PARTY.md)。
