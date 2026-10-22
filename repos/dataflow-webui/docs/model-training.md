# DataFlex 模型训练

模型训练位于 `/m/training`。它复用原生导航、输入控件、编辑保护与 Chart.js；DataFlex 源码、Python 环境和训练进程保持独立。训练元数据保存在 `backend/data/model_training/training.sqlite3`，不写入数据集数据库。`DATAFLOW_TRAINING_DIR` 可以指定独立存储目录。

当前交付通过离线配置、运行包、结果/评测、备份恢复和隔离 SSH 控制检查。所有算法的真实 GPU 验证均为 NOT_RUN。系统没有预置真实主机，不会自动安装训练依赖、下载模型或启动训练。

## 创建方案和固定输入

1. 新建方案，填写模型路径或模型 ID、模型 revision、Tokenizer、模板、任务、微调方式、步数、有效 batch 配置和种子。普通训练无需实验组；不完整方案可以保存。
2. 添加训练域、验证集和策略目标参考集。平台数据必须显式发布后绑定，训练页不会自动发布草稿。外部 JSON/JSONL 文件在导出时复制并核验；HF 数据需填写不可变 commit revision、子集和 split。
3. 选择静态或五类策略，配置组件参数。Lego 使用阶段列表，顺序为 selector → mixer → reorder → weighter。高级 JSON 与表单共用一份方案，未知字段保留；类型检查不等于完成算法语义或环境验证。
4. 保存后生成配置预览和运行包。版本冲突返回 409，必须重开检查后重新编辑，不能覆盖新版本。

组件清单基于 DataFlex `2e2a74dbe90f8b6a1394bdee37518980f1d5958d` 的源码和配置，覆盖 35 个组件/预设。清单包含构造参数、源码路径、imports、任务/模态、参考集需求和额外准备条件。内置描述在 `backend/app/templates/dataflex_catalog.json`；更新源码后可用 `backend/scripts/refresh_dataflex_catalog.py --source /path/to/DataFlex` 重新检查生成。

所有动态训练以文本 SFT 为主要配置路径。PT 的 trainer patch 具备源码证据，仍需逐算法 G1；图文发布包支持消息块转换、媒体核验和打包，但具体模型处理器与 GPU 训练未验证。动态 DPO 被拒绝。DoReMi 的三阶段需要分别建立方案并准备参考模型；TSDS/NEAR 的离线文件、NICE 的奖励模型/API、梯度投影算法的依赖及 MoE 模型不会被自动准备。

部分组件使用 `eval_dataset` 读取参考集。如果另有不同验证集，会返回具体冲突，避免静默混用；参考集 loss 不作为独立测试证据。对可识别的训练/验证重复样本，打包会拒绝。packing 固定关闭，原始 sample_id 和来源行映射会保留，但不猜测预处理后的索引。

## 运行包与独立环境

设置后端环境变量 `DATAFLEX_SOURCE_DIR=/path/to/DataFlex`，默认查找集成工作区旁的独立 DataFlex 仓库。运行包包括专用配置、数据/媒体、显式参数文件、源码快照、组件描述、commit/dirty/hash 身份、sample_map 和标准库 runner。源码只包含执行相关的 Git 跟踪文件；未跟踪组件必须在方案高级 JSON 顶层 `custom_sources` 中显式列入相对路径，并在 DataFlex 包内完成注册导入。凭据、环境、缓存、模型权重和无关输出不进入源码快照。

包内 `manifest.json` 固定每个文件的 SHA-256。导出只生成 bundle，不能证明训练运行。未配置主机时保存和导出均可用。

在独立训练环境解包后可先核验：

```sh
python runner.py verify
python runner.py preflight
```

`verify` 只检查输入；`preflight` 检查训练依赖版本、CUDA、本地模型或已缓存的固定模型 revision、参数文件和已注册组件。它不安装软件或下载模型。准备训练环境时应在独立 DataFlex checkout 中依照该版本依赖安装，不能把依赖装进生成平台环境。runner 使用包内源码的 PYTHONPATH，防止执行另一份安装源码。

HF 数据默认保留固定引用。需要联网物化数据时，在独立环境显式执行：

```sh
python prepare_data.py --allow-dataset-download
```

这会生成新的派生清单和 `prepared-<bundle_id>.zip`；通过页面“导入运行包”登记后才能使用新身份启动。该命令不会下载模型，当前未进行真实 HF 下载验证。大文件可在数据绑定高级 JSON 中显式设置 `mode: "reference"`，导出记录流式文件哈希；可通过 `execution_ref` 指定远端绝对路径（不填则沿用源文件绝对路径），SSH 预检会在训练主机重新计算哈希，缺失或不同则拒绝启动。HF 引用仍需先物化为包内输入。

手工运行需要为真实执行填写唯一身份，并使用实际 manifest 哈希：

```sh
shasum -a 256 manifest.json
python runner.py run --run-id run-unique-id --attempt attempt-unique-id --manifest <实际64位哈希>
```

运行写入 `process.json`、`result.json`、`train.log` 和 `output/`。模型留在训练主机，WebUI 导入 `result.json`。从头重跑用新 attempt；目前不提供 checkpoint 恢复。

## 固定训练主机

页面只保存 SSH config alias、绝对工作目录、训练环境 Python 绝对路径和 GPU 编号。Conda 环境通过其 Python 路径定位；不在 WebUI 中激活 shell profile 或安装环境。路径目前只接受字母、数字和 `_ . / -`，不支持空格。

WebUI 后端支持 macOS、Linux 和 Windows；固定训练主机与包内实际训练 runner 以 Linux/CUDA 为目标。Windows 客户端需提供系统 `ssh`/`sftp`，本地的配置、打包和结果管理不依赖 POSIX 模块。

先在部署后端的操作系统中配置 SSH alias、系统认证和可信 known_hosts，再保存主机，执行只读环境检查。系统 `ssh`/`sftp` 强制 BatchMode 与 StrictHostKeyChecking，不接受私钥内容，也不绕过主机验证。

启动流程为暂存上传 → ZIP/清单/成员哈希检查 → 原子发布 ready 目录 → 预检 → 独立会话 runner。默认一个活动任务，稳定幂等标识防止重复点击。runner 有主机锁和 attempt 锁，保留 PID 的启动身份。停止先核验身份，再终止训练子进程组，退出确认后才记录 stopped。

训练页打开时每 5 秒同步未确认结束的控制记录，也可使用同步按钮拉取状态和结果；指标按已保存前缀传输，日志按字节偏移同步并保留最近 1 MiB 文本窗口。半条 JSONL 暂不读取。断线保留最后状态并单独显示 disconnected；重新打开服务后仍使用已保存主机/attempt 核对，不自动重启训练。状态未知时先同步，不直接把任务判定失败。

当前 SSH/SFTP/Linux 进程兼容性、断线持续训练与真实 GPU 的 G1 尚未执行。隔离传输和本地合成子进程测试不替代实机验证。

## 结果、比较与评测

轻量结果 JSON 的 v1 必需字段：`schema_version`、`run_id`、`attempt_id`、`input_manifest_sha256`、`sequence`、`synthetic`、`status`、`metrics`、`artifacts`、`environment`、`actual_config`。可包含日志、strategy_metrics、退出码和错误。输入清单必须已登记；相同内容幂等，身份冲突、指标改写、序号回退及终态覆盖会被拒绝。失败和部分运行都可以保留。

训练日志适配 LlamaFactory `trainer_log.jsonl`；策略信号优先读取 ODM 的 `odm_weights.jsonl`。其他算法只有实际提供的结构化数值才显示曲线，缺失项显示未提供。当前没有伪造 selection IDs、token、显存或策略开销，也没有修改算法数学逻辑。

产物记录包含 `id`、`path`、`sha256`、`identity_scope` 和 `availability: remote_registered`。runner 当前核验 adapter_config/config 元数据，身份范围明确展示；这不是完整 checkpoint 权重哈希，也不是下载或备份证明。导入不能直接声称 `local_verified`。

比较默认排除 synthetic，显示模型、数据、步数、batch、种子、策略、源码和输入身份差异。相同步数不代表相同 token 或时间成本。实验组共享条件是显式声明，不能据此自动证明公平性。

评测 JSON 必需字段：`attempt_id`、`artifact_id`、`artifact_sha256`、`task`、`dataset_version`、`metric_definitions`、`metrics`、`tool_version`、`config`。产物 ID/哈希必须匹配运行记录；保留产物身份范围及配置哈希。这里只导入和展示，没有评测调度或自动数据闭环。

## 备份与恢复

页面“创建可核验备份”包括 SQLite、轻量结果和运行包，远端 checkpoint 不包含在内。损坏/丢失的训练存储不会被空库替换，原有数据生成功能仍可启动，训练 API 返回明确错误。

从 WebUI backend 目录运行：

```sh
python -m app.services.training_backups verify /path/to/backup.zip
python -m app.services.training_backups restore /path/to/backup.zip /new/empty/training-directory
```

恢复只允许新空目录，核验成员路径、内容哈希、数据库完整性和结果/包引用。恢复后设置 `DATAFLOW_TRAINING_DIR` 并重启服务；本地包路径会重定位，历史远程控制记录不会被伪装成新训练。

验证记录和资源待验清单见集成工作区 `docs/dataflex-delivery.md`。

## 与主线整合后的存储保护

训练存储使用与主线一致的跨平台锁和原子文件替换。运行包/结果导入的身份检查、元数据更新与备份相互串行，避免并发请求把已登记文件替换成另一份内容。SQLite 连接对目录名中的空格、中文、`#` 和 `%` 转义，并在操作完成后关闭；组件清单和可搬运脚本显式使用 UTF-8。

这些契约由 `backend/platform_tests/test_model_training.py` 在 Windows 与本地离线回归中检查。GPU、真实 SSH、模型下载及算法效果仍须单独验收。
