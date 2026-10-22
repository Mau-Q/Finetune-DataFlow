# 本地数据生成平台使用与交付

文中的 `DATAFLOW_WORKSPACE` 指 Finetune-DataFlow 集成仓库根目录；这些集成脚本不属于独立 WebUI 检出。执行前设置该环境变量为实际路径。

2026-10-19，M1–M6 本地交付。每位使用者独立部署，默认保留现有文件存储、服务和执行器。文本接入既有 13 步论文流程；图片 VQA 当前提供配置与运行拦截。真实文本小 PDF / 模型试跑和真实视觉调用均未在本次集成验收中执行，任务完成也不代表样本质量通过。

## 启动与更新

在已有 DataFlow 工作区根目录执行：

```sh
${DATAFLOW_WORKSPACE}/scripts/webui.sh --daemon
${DATAFLOW_WORKSPACE}/scripts/webui.sh --status
```

打开 `http://127.0.0.1:8000/`。封装脚本固定本机监听与工作区 `.venvs/dataflow/bin/python`；后台日志为 `repos/dataflow-webui/.backend.log`。前台运行使用 `${DATAFLOW_WORKSPACE}/scripts/webui.sh`，Ctrl+C 停止；后台启动对应 `${DATAFLOW_WORKSPACE}/scripts/webui.sh --stop`。状态检查只证明 WebUI API 可访问，不证明模型端点、MinerU 或 Ray worker 可用。

修改前端后，在 `repos/dataflow-webui/frontend` 运行 `npm run build`，再刷新页面。后端从 `frontend/dist` 提供静态页面；旧标签若引用已替换的资源，应重新加载。后台模式修改 Python 后需在没有任务写入时重启。单独使用 WebUI 仓库时，按 [WebUI 安装说明](profiles/webui.md) 配置环境，通过 `scripts/start.sh` 启动；不要重装已有可用环境。

## 入口与正常操作

文本生成和图片 VQA 统一从原生画布顶部「Pipeline → 自定义 Pipeline」进入。自定义页签排在模板之前并默认选中，只展示这两个入口；其他历史配置仅在此列表隐藏，未删除。两条流程均使用原来的 mainFlow、节点、端口、连线、参数面板、拖拽和自动排版。文本加载已有平台配置（没有配置时打开 13 步模板），保存和执行沿用原生工具栏。材料、任务与生成选项可通过「返回文本生成向导」访问。

MM 使用适配后的原生节点展示四步模板；参数面板可编辑资源引用、输入输出字段和变量绑定，原生「保存」将参数与拖拽坐标写回独立 MM 配置库。图片材料节点的 Switch 和顶部链接进入已有图片、服务与输出设置页面。节点描述与显示参数来自配置，外部步骤无需核心算子查询或注册，原生「Save & Run」仍受 MM 提交拦截。MM 模板的步骤顺序固定；未启用任意拓扑编辑。文本流程仍使用原有核心执行路径。

| 页面 | 路径 | 用途 |
| --- | --- | --- |
| 原始数据集 | `/#/m/materials` | 导入 PDF、图片或结构化文件，预览原文件和材料信息 |
| Prompt Manager / Schema Manager | `/#/m/prompts` / `/#/m/schemas` | 独立管理用户资源与引用 |
| 文本生成 | `/#/m?workflow=text` | 保存 13 步配置，检查条件，查看任务与收集产物 |
| 进阶画布 / 旧流程 | `/#/m` | 编辑同一 Pipeline；旧任务仍通过原面板访问 |
| 生成数据集 | `/#/m/training-datasets` | 草稿、样本编辑、发布与下载 |
| 图片 VQA | `/#/m?workflow=multimodal` | 配置代表性 MM 模板，保存重开，检查运行限制 |

文本通路：添加 PDF 原始数据集 → 在文本生成页选择材料清单 → 分配各生成/评分步骤的文本服务并核对解析脚本与 Tokenizer → 保存并检查 → 提交 → 查看任务进度和失败原因 → 选择训练产物与目标草稿收集 → 预览/整理 → 发布新版本 → 下载 JSONL 或 ZIP。检查不会试连远端；当前配置里已有服务名称也不能证明端点可用。

向导和画布共享配置 ID，画布编辑后需要保存，再通过「返回文本生成向导」重读配置。带有未保存修改时先保存。默认额外重试 0 次，即核心服务只尝试首次请求；整批进度与已完成步骤分别显示。旧的 13 步和 SFT2000 配置保留，打开它们不会自动执行。

任务保存输入副本、配置与资源内容哈希，产物区分模型原始文本、候选/中间结果、训练文件。只把训练产物收集到选定草稿；重复收集同一产物会报错。任务可完成但得到 0 条通过筛选，此时空草稿不能发布。

失败或取消的任务支持手动重跑整批，保留旧任务；完整产物存在且哈希一致才可复用。不支持任意步骤、单 QA 或解析完成后的自动续跑。应用中断留下的 running 任务，应先确认旧执行已停止，再在页面终止并重跑；不因重启自动恢复调度。详见 [任务与发布](text-generation-and-releases.md)。

图文数据可直接导入，逐个为媒体引用选择材料 ID，预览后发布下载。ZIP 中 `data.jsonl` 的图片路径指向包内 `media/`，可随包移动。发布固定样本、来源、成员和媒体副本；继续改草稿不改变旧下载。缺失或变化的媒体会阻止发布，不能靠同名文件补配。详见 [材料与训练草稿](data-library.md)。

图片 VQA 使用单独配置，选择图片与图文 SFT 目标草稿，分别设置问题/答案 Prompt、Schema、字段依赖和布局。可以在没有视觉服务时保存并刷新重开；当前独立 MM 执行桥接未启用，任何服务引用都不能绕过提交拦截。保存不会生成样本，也不改目标草稿。详见 [MM 模板](multimodal-template.md)。

Prompt / Schema 编辑影响未来提交；已固定任务继续使用旧内容与哈希。不是所有旧算子都接受任意字符串 Prompt；按 [资源契约](prompt-schema-resources.md) 使用已支持的参数与绑定。

## 持久化与备份

以下默认路径相对于 WebUI 仓库；实际路径以 `backend/app/core/config.py` 和本地配置为准。

| 位置 | 内容 |
| --- | --- |
| `backend/data/` | Pipeline、输入、Serving、任务注册表、显示偏好、用户 Prompt、Schema、材料与数据集元数据 |
| `backend/data/datasets.sqlite3` | 原始数据集、材料、草稿、样本、媒体关联、发布版本的权威元数据 |
| `backend/data/library/materials/` | 受管 PDF / 图片副本；旧 JSON 为迁移来源 |
| `backend/data/library/inputs/`、`task_inputs/` | 材料清单、任务固定输入与 PDF 副本 |
| `backend/data/library/releases/` | 已发布 JSONL / ZIP；版本元数据进入 SQLite |
| `backend/data/library/multimodal_configs.json` | MM 配置草稿 |
| `backend/cache_local/<task_id>_output/` | 步骤缓存、原始模型文本和任务固定产物 |

数据集自动备份和启动恢复已启用。备份使用 SQLite 一致性镜像与文件哈希清单；检查、隔离恢复和指定快照回退命令见 [SQLite 存储与备份](dataset-storage.md)。原地恢复前停止 API 和执行 worker，保留当前数据；不要直接复制一个打开的 SQLite 主库或单独的 WAL。备份可能含本地服务配置，应保持私有，不提交 Git。

跨机器迁移需检查绝对路径、解析环境和服务配置。发布 ZIP 使用相对媒体路径；仅恢复发布包不会恢复完整历史任务或服务。

显示偏好的隐藏列表不会删除记录。恢复可见性参见 [数据集精简视图](data-library.md)。损坏 JSON 会明确报错；先保留损坏文件并检查备份，不清空历史注册数据。

## 可重复的本地验收

在工作区根目录运行 `${DATAFLOW_WORKSPACE}/scripts/test-local.sh`；前端在 `frontend` 运行 `npm run build`。该回归不请求真实模型，不代表真实 Ray 集群、真实 PDF 生成或数据质量通过。浏览器复核时使用独立的「验收」材料和草稿，保留旧配置：

1. 导入一份新 PDF；相同字节重复导入应提示已有材料。刷新后能查看原文件并在文本向导选择它。
2. 保存无服务的文本配置，检查/提交应拒绝且不增加任务。打开画布保存并返回，核对同一个 ID、13 步、材料与重试参数。
3. 使用明确标注的离线固定样本任务验证产物收集；它不证明新 PDF 已生成。检查重复收集、发布、下载、编辑草稿后旧版本下载哈希不变。
4. 对图文版本核对 ZIP 内媒体路径和清单哈希。
5. 保存 MM 配置，刷新重开，核对图片、目标草稿、参数与布局；无视觉服务提交应拒绝。
6. 在专用验收资源上修改 Prompt，打开已固定的历史记录，核对旧内容与哈希不变。快照夹具应标明未调度/未调用模型，不能标为生成成功。
7. 打开旧 Pipeline 与旧任务，比较验收前后的原记录，确保未被覆盖。

本次 M6 的核心 158 项、WebUI 207 项与 7 个子测试、PDF 扩展 30 项全部通过；前端构建通过。浏览器验证了上述配置、离线产物与发布通路。真实模型试跑仍需单独验收。

## 原生 Pipeline UI 验收（2026-10-19）

移除独立流程画布及其配置抽屉，两个自定义入口直接使用现有 mainFlow。浏览器已验证文本 13 步与原生参数面板、MM 原生参数编辑与保存、节点拖拽、刷新恢复、Show ports，以及原生提交按钮的拦截。验收配置中结构检查输出改为 checked，问题节点拖拽后坐标保存为 (46,63)。其他 MM 配置、核心 Pipeline 注册表和任务注册表保持不变，未发起模型调用或新任务。

验证：`node --test frontend/src/hooks/dataflow/nativeMM.test.mjs`（3 项通过）、WebUI 后端全量（207 项及 7 个子测试通过）、`npm run build` 与 `git diff --check`。测试日志、验收前备份和比对位于工作区忽略目录 `outputs/native-pipeline-ui-*`、`outputs/backups/native-pipeline-ui/`；截图为 `output/playwright/native-mm-canvas.png` 和 `native-text-canvas.png`。
