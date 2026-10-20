# 论文 PDF → SFT：DataFlow / MinerU 安装核对

核对日期：2026-09-22。范围：版本、源代码接口、模型下载项和部署前置条件。
状态：研究结论及候选安装方案；未安装依赖、下载模型、连接远程主机或运行解析。本文不是已验证的环境锁文件。

## 结论

建议 DataFlow 与 MinerU 分别建立环境。新项目以 MinerU 4.0.5 作为解析候选，通过落盘文件接入 DataFlow；不要直接执行 DataFlow 现有旧版 MinerU 本地算子。

目标流程：PDF → MinerU → Markdown、结构化 JSON、图片及来源清单 → DataFlow 分块与 QA 生成 → 独立证据验证 → SFT 导出。
这是安装和接口组织建议，尚未实施新的解析适配器。生成/审核采用 API 还是自部署仍未最终选定；下方基础清单按 API 方案计算。

## 已核对的身份

| 对象 | 身份 | 核对方式 |
| --- | --- | --- |
| DataFlow main | `d70f9ef30a7da5dc9f0684c9abc3ec90d8332313` | `git ls-remote`，随后读取固定提交文件 |
| DataFlow 声明版本 | `1.0.10` | 固定提交的 `dataflow/version.py`；版本号不能代替提交身份 |
| MinerU master | `94828a88d80ab8a72c21956de0604bf14f4cc9fc` | `git ls-remote` |
| MinerU 发布包 | `4.0.5` | PyPI 元数据及 wheel 源码检查 |
| 旧版对照 | `2.5.4`，tag 提交 `61cc6886fe3edda8aa1c5b8bd2b6eaedddb8af99` | PyPI wheel 与 Git tag |

读取源码和 wheel 是静态检查，没有导入或执行这些包。wheel 的 SHA-256 与 PyPI 声明值一致：

- `mineru-4.0.5-py3-none-any.whl`：`9c80e3e10ccf9e7d49415a3044196622328eac5bcb54fc557b3846ac9e1d784d`
- `mineru-2.5.4-py3-none-any.whl`：`684457de783bf7b44c8e18ffee9f321ce774165941e6cd5d907c12ed2a30a5e4`

## 为什么不能直接安装后运行旧示例

1. DataFlow 的本地算子在当前 Python 进程内 `import mineru`，还导入 `mineru.cli.models_download.configure_model`；MinerU 4.0.5 wheel 中已没有该旧模块。仅把 MinerU 的 CLI 加入 PATH 不足以修复这一导入。
2. DataFlow 调用的是旧形式 `mineru -p ... -o ... -b ... --source local`。4.x 的一次性完整转换入口是 `mineru-kit parse`，配置与输出协议也改变了。
3. 即使选择旧版 2.5.4，示例的 `vlm-local-engine` 也不在它的 CLI 枚举中。该版支持 `pipeline`、`vlm-transformers`、`vlm-vllm-engine`、`vlm-http-client`。
4. DataFlow 将 Markdown 路径拼为 `<output>/<pdf_name>/<backend>/<pdf_name>.md`；2.5.4 的 VLM 代码实际使用 `<output>/<pdf_name>/vlm/`。算子没有在回写路径前确认文件存在。
5. DataFlow 的 `kbc` extra 固定 MinerU 2.0.6、vLLM 0.6.3；`pdf2vqa` 使用 MinerU 2.5–2.6 范围；普通 `vllm` extra 上限为 0.9.2。MinerU 4.0.5 的 Linux `full` 则要求 vLLM `>=0.19.1,<0.29.0`。这些 extras 不应合并到一个环境。

依据：[DataFlow 本地算子](https://github.com/OpenDCAI/DataFlow/blob/d70f9ef30a7da5dc9f0684c9abc3ec90d8332313/dataflow/operators/knowledge_cleaning/generate/mineru_operators.py#L434)、[DataFlow 依赖](https://github.com/OpenDCAI/DataFlow/blob/d70f9ef30a7da5dc9f0684c9abc3ec90d8332313/pyproject.toml)、[MinerU 2.5.4 CLI](https://github.com/opendatalab/MinerU/blob/61cc6886fe3edda8aa1c5b8bd2b6eaedddb8af99/mineru/cli/client.py)、[4.x 迁移文档](https://opendatalab.github.io/MinerU/reference/migration_4/)。

## 本地与远程清单

| 内容 | Mac | 远程 node01 | 版本或条件 |
| --- | --- | --- | --- |
| Git、uv、Python | 开发需要 | 运行需要 | Python 建议 3.12；环境各自独立，补丁版待部署时固定 |
| DataFlow 源码 | 克隆、可编辑安装、开发 | 同步同一提交和自定义代码 | 上述固定提交；只装基础依赖，GPU extras 按需另立环境 |
| MinerU | 本地解析调试时安装 | PDF 批量解析需要 | `mineru==4.0.5`；Linux GPU 候选为 `mineru[full]==4.0.5`，引擎版本需结合驱动验证 |
| MinerU 源码 | 修改解析器时才需克隆 | 运行发布包不必克隆 | 若改源码，使用独立 checkout 和可编辑安装 |
| 解析模型 | 本地解析时准备 | 需要 | 按下面的引擎对应项下载 |
| 原论文、来源元数据 | 留调试样本和来源记录 | 完整数据集 | 稳定 paper_id、PDF SHA-256 |
| 分块 tokenizer | 需要 | 需要 | 示例是 Qwen2.5-7B-Instruct；最终应按选定分块规则固定 revision |
| 训练长度检查 tokenizer | 沿用旧约束时需要 | 同左 | 必须对应目标模型和聊天模板，不能用分块 tokenizer 自动替代 |
| 生成/审核模型 | API 方式无需权重 | API 方式无需权重 | 模型服务选择仍待确定 |
| 自定义算子、来源映射、验证与导出 | 开发 | 同步运行 | 目前尚未实现，不是可直接下载的软件包 |

Mac 已发现 `uv` 和 `git`；没有发现 PATH 上的 `python3.11`，尚未盘点其他 Python 解释器。不能据此说 Mac 没有可用 Python。

WebUI、RayOrch、Flash-MinerU、多模态训练扩展、训练框架不列为这一基础方案的必装项。

## MinerU 4.0.5 对应模型

| 解析运行方式 | 小模型包 | VLM |
| --- | --- | --- |
| Linux NVIDIA / Torch + vLLM | `opendatalab/MinerU-4_models_torch` | `opendatalab/MinerU2.5-Pro-2605-1.2B` |
| ONNX + llama.cpp | `opendatalab/MinerU-4_models_onnx` | 注册表指定的 `jinzhenj/MinerU2.5-Pro-2605-1.2B-GGUF`，包括主 GGUF 和 mmproj |
| Apple Silicon 默认加速组合 | Torch 小模型包 | 同上 GGUF + mmproj，VLM 使用 llama.cpp |

上述仓库名称来自 4.0.5 wheel 的 `mineru/model/registry.py`。GGUF 的发布者为 `jinzhenj`，它是 MinerU 注册表选择的资源，不能把它的仓库归属写成 OpenDataLab。

因此，新版下载项不是上一轮列出的旧 `MinerU2.5-2509-1.2B`。应使用选定版本的模型下载/验证工具选择所需文件，并记录模型 revision 和文件哈希；本文未下载模型、未锁定模型 revision。

标准解析 `standard` 使用小模型与 VLM；高级解析 `advanced` 使用同一组模型增加计算，不需要再下载一套高级模型。建议先用 standard 检查双栏正文、表格、公式和页码。没有样本实测，不能声称 4.0.5 的论文解析质量优于 2.5.4。

依据：[固定源码的模型注册表](https://github.com/opendatalab/MinerU/blob/94828a88d80ab8a72c21956de0604bf14f4cc9fc/mineru/model/registry.py)、[模型下载说明](https://opendatalab.github.io/MinerU/usage/model_source/)、[解析级别](https://opendatalab.github.io/MinerU/usage/tiers/)。

## node01 的 GPU 环境仍需现场核对

历史原始日志 `/Users/rui/Documents/llm-posttraining-research/analysis/node01-run002-fastpath-20260914/nvidia-before-976.txt` 记录四张 L40、每卡 46068 MiB、驱动 550.127.08；这是 9 月 14 日证据，本轮未 SSH 检查。

当前 MinerU 官方 Dockerfile 使用 vLLM 0.21.0 / CUDA 13.0，并给出 CUDA 12.9 镜像备选。CUDA 13.x 的常规驱动下限是 580，不能把默认镜像当作已适配历史 550 驱动。CUDA 12.x 的 minor compatibility 也有 PTX 和新特性限制，不能仅凭主版本一致宣称新版 vLLM 可用。

部署前只读核对：当前驱动、GPU 使用情况、系统/架构/glibc、磁盘、Docker GPU runtime、包源和模型源连通性。然后选定引擎及其 CUDA/PyTorch 配套版本，在单张空闲卡上验证。本文不提出升级共享主机驱动，也不复用已经清理的旧 RUN002 镜像。

若保持历史驱动，需单独评估可用 CUDA 构建或 llama.cpp 路线；它们目前都没有运行证据。故本轮能固定 DataFlow 代码与 MinerU 包版本，不能诚实地给出“已验证可运行”的完整 GPU 锁文件。

依据：[固定 Dockerfile](https://github.com/opendatalab/MinerU/blob/94828a88d80ab8a72c21956de0604bf14f4cc9fc/docker/global/Dockerfile)、[NVIDIA 兼容表](https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html)。

## 接入与验证要求

- MinerU 独立进程生成完整解析产物；DataFlow 读取既有 Markdown 和结构化记录。需要显式适配来源映射，不能把 Markdown 文件名当作页码证据。
- 使用 `mineru-kit parse` 的完整文档转换入口，保存 ZIP/结构化 JSON 和图片。`mineru parse` 的默认前 10 页及 continuation 响应不适合直接当成完整论文数据；它的 `--json` 也不是 MiddleJson。
- 保留解析版本、模型身份、tier、原 PDF 哈希、真实页码/块号和可用坐标。禁止在新解析文本上沿用旧 chunk 哈希。
- DataFlow 官方示例仅到 `QA_pairs` 和 `QA_metadata`，还需独立事实支持检查及最终 SFT 格式导出。
- 安装验证分开记录：依赖解析/导入 → 模型文件完整性 → 单论文实际推理 → 结构与原页抽查 → 来源映射 → QA 验证/导出。前一项通过不代表后一项通过。
- 最终锁定所有 Python 依赖、引擎/容器 digest、模型 revision 后，再进行批量处理。

依据：[DataFlow 固定示例](https://github.com/OpenDCAI/DataFlow/blob/d70f9ef30a7da5dc9f0684c9abc3ec90d8332313/dataflow/statics/pipelines/api_pipelines/kbcleaning_pipeline.py)、[MinerU 输出约定](https://opendatalab.github.io/MinerU/reference/output_files/)。

## 检查范围与限制

本轮完成官方文档、固定源码、PyPI 元数据和两个 wheel 的静态检查；重新读取了旧 GPU 原始日志。未修改上游源码、未克隆仓库、未安装 Python 包、未下载模型、未调用生成/审核模型、未执行远程操作。唯一持久化产物是本报告。

本地 Python HTTPS 请求遇到证书链错误，改用保持证书校验的系统 curl 后成功。GitHub REST API 返回 403，提交身份改用 `git ls-remote` 获取；未尝试绕过访问控制。网页 main 缓存与固定提交文本有行号差异，最终判断以固定提交和 wheel 为准。
