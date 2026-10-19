# DataFlow / DataFlow-MM 算子、Pipeline 与兼容性调研

日期：2026-10-19。结论：**PARTIAL_REUSE**。文本路线继续使用核心 DataFlow；视觉路线优先复用 DataFlow-MM 的 API VQA 算子，在独立进程中执行，通过 JSON 文件与核心格式转换和数据集管理交换产物。当前没有开发平台，也没有将两套 `dataflow` 包混装到原运行环境。

真实本地 PDF 解析、官方 MM 两步 VQA 流程的 HTTP 协议链路、跨进程结果交换和包含媒体的训练包导出已验证。生成调用使用本地确定性测试 API，**没有真实视觉模型推理，不证明生成质量或任意真实材料的适用性**。

## 1. 范围、版本与目录

必需能力：原始材料准备、文本与视觉语言 SFT 生成、可自定义 Prompt/Schema、结构化结果及媒体导出。重点复用解析、视觉请求构造、批量问答与格式转换。RAG、视频音频、文生图、模型部署、平台业务开发均不在本轮范围。

| 对象 | 本轮固定版本或状态 |
| --- | --- |
| 核心 DataFlow | `repos/dataflow`，`769a99e0563a7ad63b451dc0f3a9854cd9c1a182`，包版本 `1.0.10` |
| WebUI | `repos/dataflow-webui`，`717c38a211dc547726f086b1388ef13ff2eded04` |
| DataFlow-MM | `repos/dataflow-mm`，`155253460f6f2e50705a3e779f259b382a382822`，源码版本 `0.0.1` |
| MM 来源 | `https://github.com/OpenDCAI/DataFlow-MM.git`，浅克隆，独立 Git 仓库 |
| MM 维护快照 | 官方仓库未归档，最近推送 `2026-04-13T09:12:34Z`；不能据此承诺持续维护 |
| 许可证 | 两套源码的 LICENSE 均为 Apache-2.0；模型权重和新增依赖的许可不由此推定 |
| 原环境 | `.venvs/dataflow`，Python 3.12.15；没有向其中安装或升级 MM 依赖 |
| MM 源码 PoC 环境 | `.venvs/dataflow-mm-research`，独立解释器入口，使用 `.pth` 引用原环境已有依赖，并通过 `PYTHONPATH` 固定 MM 源码 |

PoC 环境是**复用已有依赖的源码执行环境**，不是完整独立依赖安装验收。已有 torch 为 `2.14.0`，不满足 MM 声明的 `torch<=2.8.0`；本轮 API 路线可运行，不能外推到本地 GPU 路线。

检索渠道包括本地源码与 Git、官方仓库源码和元数据、实际包构建、导入与运行探针。官方 GitHub REST 通过 `gh api` 可用。没有检索替代框架、下载 Hugging Face 模型、安装 MM 全量依赖或运行远端模型；这些不属于此次最小链路所需。完整静态清单见[源码索引](dataflow-vision-source-index.md)，签名和 Pipeline 的实际 `run()` 调用在本地 `outputs/dataflow-mm-research-2026-10-19/inventory.json`。

## 2. 算子清单及用途判断

静态扫描覆盖核心 `core_text` 19 个、`text_sft` 18 个、`knowledge_cleaning` 10 个、`core_vision` 1 个、`pdf2vqa` 5 个注册声明；MM 的 `core_vision` 有 56 个注册类，其中 52 个在父模块声明惰性导出。相关 Pipeline 类分别索引到 10 和 31 个，包含 CPU/GPU 变体和超出首版的高级视觉任务。**这是源码声明数，不是可运行能力数。**

### 文本与 PDF 路线

| 组件 | 实际作用 | 复用判断 |
| --- | --- | --- |
| 本地 `MinerU4PDFParser` / `MinerU4PageExtractor` | 独立 MinerU 4 环境解析 PDF；从 ZIP 提取逐页内容和位置 | 继续复用；真实单页 CLI 解析和现有 PageExtractor 已执行 |
| `PaperEvidenceChunker` / 本地结构切分扩展 | 已有证据分块方案 | 可复用，不为视觉路线重写文本分块 |
| `PromptedGenerator` | 单列文本加提示词，传递 `json_schema` 到服务 | 已用真实算子与本地 HTTP 执行；空输入与失败仍需上层记录 |
| `FormatStrPromptedGenerator` | 多字段到命名模板，支持结构化输出参数 | 可复用；本轮做源码核查，未单独执行 |
| `Text2QAGenerator` / `Text2MultiHopQAGenerator` | 文本专用 QA 生成策略 | 任务模板候选，不固定为唯一生成方式 |
| `CondorGenerator` / `CondorRefiner` / `AlpagasusFilter` | 指令合成、改写和评分过滤 | 已有模板；不是把用户 PDF 自动变成视觉 SFT 的流程 |
| 本地 `SFT2000Generator` / `Verifier` / `Exporter` | 已冻结的论文 QA 基线及规则 | 保留现有实验用途，不把固定模型与提示词约束推广为通用平台规则 |

### 视觉路线

| 组件 | 实际接口与能力 | 实测或限制 |
| --- | --- | --- |
| 核心 `PromptedVQAGenerator` | `llm_serving`；`run(input_key, output_key)` | 已执行；配合核心 VLM 客户端，每行是图片路径、统一提示词；不是 MM 的对话接口 |
| 核心 `APIVLMServing_openai` | 单图/多图 API 方法，部分方法接收 `json_schema` | 图片字节与 Schema 转发已执行；不能直接替代 MM messages 接口 |
| MM `PromptedVQAGenerator` | `serving`；`input_conversation_key` / `input_prompt_key` / `input_image_key` | 官方两步 Pipeline 已执行，适合作为首版视觉问答起点 |
| MM `PromptTemplatedVQAGenerator` | 模板字段映射，多图，`NamedPlaceholderPromptTemplate` | 动态模板与双图实际 HTTP 请求已验证；其模板不是核心已注册的 PromptABC |
| MM `BatchVQAGenerator` | 一张图对应问题列表，批量展开后还原答案列表 | 单图两问题已执行 |
| MM `FixPromptedVQAGenerator` | 固定提示词的图文生成，检查有效媒体 | 源码已核查，适合统一图片描述；未单独执行 |
| MM `WikiQARefiner` | 解析特定 Article + QA 文本为 `context/qas` | 可导入，属于特定文本协议；不等于通用 JSON Schema 解析 |
| 核心 `VQAFormatter` | 从 `vqa_pair` 转 `messages/images` | 已实际执行；需外层媒体定位、打包与完整性检查 |
| MM `ImageConsistencyFilter` | 通过文本 NLI 检查 caption、question、answer 的一致性 | 仅导入与源码核查；需额外模型，不能当作直接核验原图片事实 |
| MM `ImageDeduplicateFilter` | CLIP 特征近重复检测 | 当前导入因缺少 `clip` 失败；模型权重也未准备，不纳入基本链路 |
| MM `VisionDependentFilter` | 尝试无图回答再判断视觉依赖 | 与现有 MM API 服务的方法名不一致，已复现 AttributeError，不能直接接入 |
| MM `VisualDependencyRefiner` | 多次选项打乱、图文对照检查选择题视觉依赖 | 可导入，源码要求 MCQ 结构和多次调用，不作为首版普通 QA 默认过滤器 |
| 其他评分、检测、分割算子 | CLIP/VQA 分数、bbox、分割等专门任务 | 见静态索引，未验证运行；不因存在源码就纳入首版 |

## 3. Pipeline 比较

| 候选 | 覆盖与用途 | 缺少或不适配部分 | 决定 |
| --- | --- | --- | --- |
| 核心 DataFlow 文本路线 | 已有 PDF 准备、通用文本生成与 SFT 模板，当前 WebUI 基于它 | 视觉任务能力较薄，管理层解耦仍需补齐 | 保留文本主线 |
| MM `api_pipelines/image_vqa.py` | 图片 + 对话 → 问题 → 图片 + 问题 → 答案，真实 `forward()` 已执行 | 模板覆盖密钥环境变量、忽略传入 serving；无通用 Schema 验证、媒体打包或平台恢复 | 选作视觉最小流程，配置和结果边界需要适配 |
| 核心 `pdf_vqa_extract_pipeline.py` | 合并 PDF、MinerU 转换、抽取现成题目与答案、合并和格式转换 | 题目抽取专用；依赖旧内容列表及 Flash-MinerU GPU 示例路径，与本地 MinerU 4 不直通 | 只复用合适组件，不作为通用资料视觉合成默认流程 |

MM `image_caption.py` 是单步描述；`image_contextvqa.py` 是生成文章与 QA 后用 `WikiQARefiner` 解析；`image_gcot_api_pipeline.py`、`image_scale_caption_api_pipeline.py`、`image_visual_only_mcq_api_pipeline.py` 分别增加推理、细节核验或选择题视觉依赖等步骤。它们提供后续参考，但会引入额外协议、模型调用或依赖，本轮未整条执行。

GPU Pipeline、视频音频、图像生成/编辑不属于已确认的视觉语言 SFT 最小需求，暂不选用。避免为调用图片 API 安装整套多媒体计算栈。

## 4. 已验证的兼容性问题

1. **同名包覆盖。** 两个项目都提供 `dataflow`。将两仓库按不同顺序放入 `PYTHONPATH`，实际导入路径与同名算子签名随顺序切换；它们不能被当作同一 Python 进程里可自由拼接的两个独立插件。
2. **基础接口不同。** 核心具有 `dataflow.pipeline.PipelineABC`，当前 MM 仓库没有对应目录；两边的 Operator/Serving 基类也来自不同包实现。DataFrame/JSON 文件适合作为交换边界，Python 对象不能直接跨进程复用。
3. **WebUI 没有现成 MM 接口。** Serving 注册表仅开放文本 `APILLMServing_request`；现有执行器按参数名 `llm_serving` 注入，MM 的主要算子使用 `serving`。当前扩展列表只有 `paper_dataflow`，不是安装 MM 后自动适配。
4. **Schema 路径不同。** 核心文本生成器和核心部分 VLM 调用支持 Schema 参数；MM 的 `generate_from_input_messages()` 没有 `json_schema` 参数。首个适配应先保证响应解析和本地 Schema 验证，不能声称已经使用服务端严格约束；如增加服务端约束需明确实现与验证。
5. **解析产物不兼容。** 本地 MinerU 4 ZIP 包含 `structured_content.json` 和 `images/...`，实测没有 `*_content_list.json`。核心 PDF2VQA 的 `MinerU2LLMInputOperator` 搜索后者，不存在直接连接；PoC 从真实 ZIP 提取图片，通过显式映射接入 MM。
6. **缺图可能变纯文本。** MM `PromptedVQAGenerator` 的图片列缺失时仍调用文本模式；已核验请求没有任何图像。视觉任务必须在调用前检查媒体。
7. **失败文本没有状态。** MM API 请求失败时可能返回 `Error: ...`，算子继续写入普通结果。已用 HTTP 400 复现。上层需独立失败状态，不能把该字符串当答案。
8. **行对齐与恢复。** 核心简单 VQA 跳过空图片路径后将短结果写回原 DataFrame，实测报长度不匹配；MM FileStorage 的步骤缓存也不等于按输入记录恢复。这些属于未来薄适配职责。
9. **重试参数含义不同。** 核心 `APILLMServing_request.max_retries` 实际循环次数包含第一次请求，`0` 不发请求。PoC 使用 `1` 表示单次尝试；MM OpenAI SDK 的重试另有默认值，PoC 明确关闭。平台“额外重试次数为 0”不能原样映射给所有客户端。
10. **媒体导出不完整。** `VQAFormatter` 按图片 basename 索引工作目录，无法据此保证来源唯一；不存在的图片也可能进入结果，已复现。本轮加了研究用的显式字段映射、内容哈希命名、复制与相对路径打包，尚不是平台适配器。
11. **可导入不等于可调用。** `VisionDependentFilter` 能导入，但调用了 API 服务不存在的 `generate_from_input_with_message`（单数）；MM 服务提供的是 `generate_from_input_messages`，探针复现了接口错误。

MM 全量 requirements 包括 torch 上限和大量图像、音频、视频依赖。当前共享依赖快照缺少其中若干包，`ImageDeduplicateFilter` 导入已因 `clip` 缺失失败。没有为了通过导入审计修改原环境。

另在源码副本构建 wheel 成功，产物包含视觉算子及 serving 子包；不代表全量依赖安装成功。仓库 `pyproject.toml` 中仅列顶层 package 也不能脱离 `MANIFEST.in` 就断定 wheel 漏包，本轮实际检查了构建产物。

## 5. 最小链路实测

可复现最终结果在 `outputs/dataflow-mm-research-2026-10-19/reproduction/`；初次运行、构建、导入和命名空间审计位于其上级目录。

| 测试 | 输入与真实执行部分 | 结果 |
| --- | --- | --- |
| PDF 解析 | 合成 1 页 PDF，含文字、红色方块、公式及表格样式文字；真实本地 MinerU 4 standard | 1 页，提取图片；不据此宣称复杂公式或表格已准确结构化 |
| PDF → 文本 QA | 真实 `MinerU4PageExtractor` → 核心 `PromptedGenerator` → 本地测试 HTTP API | 成功取页、发送文本与 Schema、保存 JSON；答案为确定性夹具，不是真实模型生成 |
| 核心图片调用 | 独立 PNG、PDF 整页渲染 PNG、MinerU 裁图 JPG，共 3 条 | 真实 VQA 算子和客户端发送图像，服务器核对解码后的 SHA-256 |
| MM 两步 VQA | 同一批 3 条，执行官方 `ImageVQAPipeline.forward()`；仅替换服务配置、输入路径和缓存 | 3 次生成问题 + 3 次回答；第二步收到第一步问题和原图 |
| MM 模板与多图 | 两图 + `topic` 字段 → `PromptTemplatedVQAGenerator` | 实际请求含两张图片及正确渲染文本 |
| MM 批量问答 | 一张图与两个问题 → `BatchVQAGenerator` | 展平发送、还原两个回答 |
| 跨环境导出 | MM JSON 文件 → 显式字段映射 → 核心 `VQAFormatter` → JSONL + images ZIP | 3 条；图片存在、相对路径可解析、`<image>` 数量一致 |
| 故障探针 | 核心空行、MM 缺图、HTTP 400、视觉依赖过滤器接口、Formatter 缺图 | 预期缺陷均复现并留存 |
| 发行与入口 | MM wheel 构建；沙盒 `python -m dataflow.cli init` | 构建成功，初始化生成 47 个 Python 文件，含图片 VQA 模板 |

最终核心探针 6 项、MM 探针 7 项、导出探针 6 项检查完成，包含预期缺陷的复现断言，不是 19 项生成质量测试。脚本只对 loopback API 使用伪密钥，不读取现有 Serving 的真实密钥或联系示例远端地址。上游示例的环境变量覆盖被隔离且恢复，测试覆盖了原服务配置而未编辑上游源码。

未验证：真实 VLM 的识图和 QA 质量、真实模型 API 的 Schema 支持、Linux/CUDA、本地 GPU 推理、完整 MM requirements 的独立安装、WebUI/Ray 的 MM 运行、长任务恢复与大规模吞吐。不能将这些列为已完成能力。

## 6. 对方案的更新

最小组合为：

```text
文本：现有材料准备 → 核心通用文本生成 → Schema 验证 → 数据集产物
视觉：图片 / PDF 页面或解析裁图 → MM 图片 VQA → Schema 验证 → 数据集产物
                                             ↓ JSON 文件
                              核心格式转换 + 明确媒体清单与打包
```

可直接复用指**在各自环境中复用原算子计算逻辑**：本地 PDF 准备、核心文本生成、MM VQA/动态模板/批量问答、核心格式转换。它不代表直接注册进当前 WebUI。

必须适配：输入字段与有效图片检查、Prompt/Schema 解析与运行快照、MM 执行入口与服务配置、响应结构验证和失败状态、图片引用与导出打包、后续按记录恢复。PoC 已证明文件边界可行，尚未实现这些平台模块。

首版不引入完整 MM 模型部署和高级评分流水线。先固定 API 图片 VQA 模板；图像区域、复杂视觉推理或专用质量过滤在确有需求时分别验证。下一步可先选择一个真实视觉服务做 1–3 条联调，再进入平台接入；缺少真实服务时，应保持“协议链路通过、真实模型待验”的状态。

## 7. 复现

源码固定：`git -C repos/dataflow-mm rev-parse HEAD` 应为上文提交。MM 研究环境建立方式如下，`.pth` 只借用已有包，不会向核心环境安装依赖：

```sh
uv venv --python .venvs/dataflow/bin/python .venvs/dataflow-mm-research
.venvs/dataflow-mm-research/bin/python - <<'PY'
import site
from pathlib import Path
p = Path(site.getsitepackages()[0]) / 'research_dependencies.pth'
p.write_text(str(Path('.venvs/dataflow/lib/python3.12/site-packages').resolve()) + '\n')
PY
```

若环境已存在，复用即可；不要为复现覆盖已有环境。选择不存在的输出目录依次执行：

```sh
.venvs/dataflow/bin/python scripts/research/vision_compatibility_probe.py \
  --engine prepare --output outputs/vision-poc-fresh

PYTHONPATH="$PWD/repos/dataflow" .venvs/dataflow/bin/python \
  scripts/research/vision_compatibility_probe.py --engine core --output outputs/vision-poc-fresh

PYTHONPATH="$PWD/repos/dataflow-mm" .venvs/dataflow-mm-research/bin/python \
  scripts/research/vision_compatibility_probe.py --engine mm --output outputs/vision-poc-fresh

PYTHONPATH="$PWD/repos/dataflow" .venvs/dataflow/bin/python \
  scripts/research/vision_compatibility_probe.py --engine export --output outputs/vision-poc-fresh

.venvs/dataflow/bin/python scripts/research/inventory_dataflow_vision.py
```

`prepare` 实际运行本地 MinerU，超时 180 秒；需要现有本地模型与解析环境。其余生成请求只发往进程内启动的 `127.0.0.1` 临时端口。服务在退出时关闭，不持久修改模型配置。原始 PDF、解析 ZIP、HTTP 证据、JSON 报告和训练包均保留用于审阅；它们位于 Git 忽略的 `outputs/`，不随代码提交分发。

## 8. 证据与变更边界

研究脚本：[链路探针](../../scripts/research/vision_compatibility_probe.py)、[清单生成器](../../scripts/research/inventory_dataflow_vision.py)。源码索引中的路径链接到当前工作区各独立仓库；外部分发需按固定提交获取源码。

机器证据：`inventory.json`、`import-audit.json`、`namespace-probe.json`、`wheel-inspection.json`、`cli-init-report.json`、`upstream-metadata.json`；最终链路证据为 `reproduction/prepare-report.json`、`reproduction/core/report.json`、`reproduction/mm/report.json`、`reproduction/export-report.json` 和 `reproduction/training-package.zip`。

已知上游问题：官方 [Issue #5](https://github.com/OpenDCAI/DataFlow-MM/issues/5) 仍开放，标题涉及 LLM/VLM Serving 混用检查；正文为空，不能据此推断具体实现。本文具体兼容性判断以固定源码与本轮探针为依据。

本轮新增 MM 克隆、PoC 解释器入口、研究脚本、研究证据和文档。未修改核心 DataFlow、MM 或 WebUI 的源码，未向原虚拟环境安装依赖，未修改现有 Pipeline/Serving 注册文件。原有 `pipelines/SFT-PIPELINE-OPERATORS.md` 删除保持原状。
