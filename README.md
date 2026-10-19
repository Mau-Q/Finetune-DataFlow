# DataFlow 本地工作区

这是 Mac Apple Silicon 的本地安装工作区。上游源码分别保存在 `repos/dataflow` 和 `repos/dataflow-webui`，使用独立 Git 历史。版本与验收记录见 `INSTALLATION_STATUS.md`；安装前调研见 `INSTALLATION_RESEARCH.md`。

本工作区与两个嵌套仓库分别由 Git 管理。当前分支、基线提交和未跟踪运行数据的边界见 [WORKSPACE_BASELINE.md](WORKSPACE_BASELINE.md)。

## 启动 WebUI

在本目录执行：

```sh
./scripts/webui.sh --daemon
./scripts/webui.sh --status
```

打开 <http://127.0.0.1:8000/>。MCP 地址为 `http://127.0.0.1:8000/mcp`。停止服务：

```sh
./scripts/webui.sh --stop
```

服务日志在 `repos/dataflow-webui/.backend.log`。服务仅监听本机，不自动设置开机启动。

## 数据生成平台（M1–M6）

本地框架集成回归与交付已完成，覆盖材料、资源、文本任务、草稿、发布导出和图片 VQA 配置。入口与备份说明见 [使用手册](repos/dataflow-webui/docs/local-data-platform.md)，验收证据和真实运行待验项见 [M6 交付记录](docs/platform-m6-delivery.md)。本轮未执行真实模型调用。

## 本地解析 PDF

```sh
./scripts/mineru.sh parse /绝对路径/论文.pdf -o outputs/paper.zip --format zip --tier standard
```

默认解析全部页；小规模试跑加 `--pages 1-3`。ZIP 保存 Markdown、结构化 JSON 和图片等解析产物。原始 PDF 应保留。DataFlow 1.0.10 内置旧 MinerU 算子的 API 与 MinerU 4 不兼容，因此使用独立解析进程，再将文件交给 DataFlow；不要直接运行旧的 PDF 一键示例。

MinerU 与 DataFlow 的 Python 分别为 `.venvs/mineru/bin/python` 和 `.venvs/dataflow/bin/python`。模型存放在 `models/mineru`，运行脚本强制使用本地模型。显式下载或更新模型时可运行：

```sh
./scripts/mineru.sh models download --tier standard --small-backend torch --vlm-engine llama-cpp --source huggingface
./scripts/mineru.sh models verify --tier standard --small-backend torch --vlm-engine llama-cpp
```

## 开发与接入

已配置并验证“论文 PDF → 证据分块（演示，无 LLM）”Pipeline，可从 WebUI 顶部 Pipeline 列表打开。三个本地算子已经自动注册到 `paper` 类别；配置、后端同步命令、运行结果和后续 QA/SFT 接入说明见 [pipelines/README.md](pipelines/README.md)。

- DataFlow 以 editable 模式安装，修改 `repos/dataflow` 会直接影响运行环境。
- `extensions/paper-dataflow` 是自定义算子、提示模板、流水线的本地扩展工作区。
- `models/tokenizers/Qwen2.5-7B-Instruct` 仅包含分块 tokenizer，不含 7B 模型权重；训练长度检查仍须使用最终目标模型对应的 tokenizer 和聊天模板。
- DataFlow Skills 来自 WebUI 的 canonical 源，经上游安装器生成后由 `.agents/skills` 引用。
- `.codex/config.toml` 使用项目级 MCP 配置。Codex 仅对受信任项目加载该配置；如当前会话尚未显示新工具，重载 MCP 或重新打开本项目。参见 [OpenAI MCP 配置文档](https://learn.chatgpt.com/docs/extend/mcp?surface=cli) 和 [Skills 发现规则](https://learn.chatgpt.com/docs/build-skills)。
- QA 生成、LLM 审核需要另行选择模型并配置 API Serving。安装验收不代表这些生成流程已通过质量评估。

本地无 API 检查：

```sh
.venvs/dataflow/bin/python scripts/smoke-dataflow.py
NO_PROXY=localhost,127.0.0.1 .venvs/dataflow/bin/python scripts/smoke-mcp.py
```

本地回归测试使用同一 DataFlow 环境。首次运行先安装测试依赖，然后执行：

```sh
uv pip install --python .venvs/dataflow/bin/python -r locks/dataflow-test.txt
./scripts/test-local.sh
```

脚本依次运行 DataFlow CPU 测试、WebUI 后端测试和本地扩展测试。DataFlow 阶段排除 `gpu` 标记的测试（其中包括需要远端模型仓库的加载测试）；这些结果不代表上游完整测试或真实模型运行已经通过。

依赖冻结清单和安装日志分别在 `locks/`、`logs/`。首次重建 `fasttext-wheel` 在此 Mac 上使用 `CC=/usr/bin/clang CXX=/usr/bin/clang++`；安装 uv 包使用 `UV_SYSTEM_CERTS=true`。
