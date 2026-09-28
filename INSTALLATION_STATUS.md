# 本地安装与验证记录

完成日期：2026-09-22。工作目录：`/Users/rui/Documents/DataFlow`。

## 已安装

| 组件 | 版本 / 来源 | 本地位置 |
| --- | --- | --- |
| DataFlow 源码 | `OpenDCAI/DataFlow`，`d70f9ef30a7da5dc9f0684c9abc3ec90d8332313`，1.0.10 | `repos/dataflow`，editable 安装到 `.venvs/dataflow` |
| DataFlow WebUI / MCP / Skills | `OpenDCAI/DataFlow-WebUI`，`2e95d40ad504a6b4ba9e71d335ad85e3b12a92b6`，webui profile | `repos/dataflow-webui` |
| MinerU | PyPI `mineru==4.0.5` | `.venvs/mineru` |
| MinerU Torch 小模型 | Hugging Face `opendatalab/MinerU-4_models_torch` | `models/mineru/models/MinerU-4_models_torch` |
| MinerU GGUF 视觉模型 | 上游注册表指定的 `jinzhenj/MinerU2.5-Pro-2605-1.2B-GGUF`；Q8_0 + mmproj | `models/mineru/models/MinerU2.5-Pro-2605-1.2B-GGUF` |
| 分块 tokenizer | `Qwen/Qwen2.5-7B-Instruct`，revision `a09a35458c702b33eeacc393d103063234e8bc28` | `models/tokenizers/Qwen2.5-7B-Instruct` |
| 自定义扩展脚手架 | 上述 DataFlow 内置 cookiecutter，`paper-dataflow==0.0.1` | `extensions/paper-dataflow`，editable 安装 |

两个虚拟环境均使用 Homebrew Python 3.12.14。GGUF 来自 MinerU 上游选择的社区发布仓库。模型文件与 tokenizer 共约 2.147 GB，文件大小、SHA-256 和 Hugging Face revision/etag 记录于 `locks/models.json`。

Skills 共 5 个：`generating-dataflow-pipeline`、`dataflow-dev`、`dataflow-operator-builder`、`prompt-template-builder`、`core_text`（参考文档）。上游安装器生成 `.codex/skills`，当前工作区通过 `.agents/skills` 符号链接发现。源头仍是 WebUI 的 `skills/canonical`。

## 通过的实际检查

| 检查 | 结果 / 证据 |
| --- | --- |
| 上游安装器 prerequisites、dry-run、正式安装 | webui profile 全部通过；正式安装的 5 个边界路径未发生变化。`logs/webui-install.log` |
| 两个 Python 环境依赖一致性 | `uv pip check` 通过；DataFlow 环境含扩展共 256 个包，MinerU 环境 117 个包 |
| editable 来源 | `open-dataflow` 与 `paper-dataflow` 的 `direct_url.json` 均指向本地源码，`editable=true` |
| WebUI 前端 | `npm run build` 通过。`logs/webui-build.log` |
| HTTP 与 MCP | 首页与算子分类 API 返回成功；Streamable HTTP initialize、list_tools 和真实 `list_operator_categories` 调用通过，20 个 MCP 工具。`logs/mcp-smoke.json` |
| WebUI 页面 | 浏览器实际加载页面；初始化中文偏好后重新加载成功，无新增的 language-null 错误 |
| 注册资源 | 14 类、197 个算子，52 份上游示例数据；运行时 JSON/YAML 注册文件全部可解析 |
| DataFlow 本地运行 | SHA-256 精确去重 3 条→2 条；本地 tokenizer 编码/解码通过。`logs/dataflow-smoke.log` |
| 扩展注册 | 2 个示例算子、1 个示例提示模板成功注册。`logs/extension-smoke.log` |
| MinerU 模型 | basic / standard 所需模型 verify 通过。`logs/mineru-model-verify.log` |
| MinerU 解析 | basic、standard 均实际解析单页 PDF；两份输出保留标题、正文、表格。`outputs/mineru-basic.zip`、`outputs/mineru-standard.zip` |
| 加速 | MinerU 环境中 `torch.backends.mps.is_available()` 为 true；standard 实际初始化 llama-cpp 视觉推理引擎 |
| Codex 本地配置 | 在工作区根目录执行 `codex mcp get dataflow --json` 可读取项目配置；未写全局 Codex 配置 |
| Codex adapter 兼容修正 | 当前 CLI 参数与 5 种 JSON 事件离线检查通过。`logs/codex-adapter-check.log`；未调用付费模型 |

验收 PDF 为本次生成的 `data/smoke/installation-check.pdf`。它是安装冒烟测试，不是论文 OCR 质量基准，也不代表所有算子均已运行过。

## 本地兼容处理

- `fasttext-wheel==0.9.2` 在 Homebrew LLVM 23 下编译失败；改用 `CC=/usr/bin/clang CXX=/usr/bin/clang++` 后构建成功。原失败日志和成功日志均保留。
- 模型下载沿用已有 SOCKS 代理，补装 `httpx[socks]`。未修改代理设置。
- WebUI `backend/app/mcp_server.py`：从旧 SSE `mount()` 改为 `mount_http()`，匹配当前 Codex Streamable HTTP 客户端。
- WebUI `codex_adapter.py`：`--cwd` 改为当前 `--cd`；适配 thread/item/turn JSON 事件，并显式传入本地 MCP URL。命令行接入不依赖嵌套源码仓库的信任状态。
- 初始化偏好为 `language=cn`，避免上游首次启动读取空偏好产生空值错误。
- 排查时并行导入了两次 WebUI，暴露了示例数据索引写入竞争；本次生成的异常索引保存在 `logs/data_registry.concurrent-import.yaml`，串行重建后 52 条示例记录与全部注册文件验证通过。之后没有再并行初始化 WebUI。
- 当前服务通过独立进程会话启动，避免工具命令退出时终止普通 nohup 子进程。PID 文件仍由上游停止脚本识别。用户终端可正常使用 `scripts/webui.sh`。
- `frontend/yarn.lock` 的变更来自 npm 安装；实际 npm 解析结果保存在前端 `package-lock.json`。

## 运行与边界

- 当前服务监听 `127.0.0.1:8000`。入口：<http://127.0.0.1:8000/>，MCP：`http://127.0.0.1:8000/mcp`。
- 不自动开机启动；启动、状态、停止及 PDF 命令见 `README.md`。
- 项目 `.codex/config.toml` 已配置。当前对话不会据此自动获得已经验证过的 MCP SDK 调用以外的工具状态；客户端需自行重载新配置。
- 后续已配置 Qwen 生成与 DeepSeek Pro 审核服务，修复 `configs` 传递并各完成一条真实 JSON 连通测试，详见 `pipelines/SERVING_STATUS.md`。尚未运行批量 QA 生成、审核或 SFT 训练。WebUI 内嵌 Codex 聊天仍仅做适配层离线验证。
- 后续已启用 WebUI 自动导入 `paper_dataflow`，新增 3 个 `paper` 类别算子。演示 PDF 经后端任务 `8273f63acb84` 完成解析、逐页提取、证据分块；前端画布同步已验证。细节见 `pipelines/README.md`、`logs/paper-prepare.verification.json`。原表格保留安装时快照计数，当前共 202 个算子（增加 2 个扩展示例和 3 个实际算子）。
- MinerU 4 通过独立 CLI 输出文件，与 DataFlow 的旧 MinerU 算子隔离。旧 PDF 一键示例不能直接视为可运行。
- 没有安装 CUDA/vLLM、RayOrch 集群、全量领域模型或训练权重。WebUI 依赖的 Ray Python 包已安装。
- 安装完成时工作目录占用约 **5.8 GiB**（不含工作目录外的包管理器缓存）；系统实时空闲约 **81.18 GB / 75.61 GiB**。磁盘数值会随系统运行变化。

依赖冻结：`locks/dataflow.txt`、`locks/mineru.txt`；模型完整性与来源：`locks/models.json`。
