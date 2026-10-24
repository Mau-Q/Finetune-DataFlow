# 目录职责与命名约定

更新：2026-10-24。适用于 Mac 开发目录与学校 DataFlow 部署。已有环境、运行目录、任务 ID 和证据路径保持原状；本约定用于新目录和后续分批迁移。

## 先按用途找内容

Mac 根目录为 `/Users/rui/Documents/DataFlow`。Core、WebUI、DataFlex 已作为普通源码目录纳入同一个 Git 仓库；只有可选 MM 仍是子模块。

| 目录 | 保存什么 | 管理方式 |
| --- | --- | --- |
| `repos/`、`extensions/`、`tools/` | 组件源码、本地扩展、个人执行器 | 总仓库 Git；不要按组件重复提交 |
| `scripts/` | 安装、启动、回归、维护工具；部分旧论文实验脚本仍在此 | 新增工具按用途组织，历史脚本迁移前核对相对路径 |
| `pipelines/` | 可复用流程及历史论文实验配置 | 通用流程与带本机绑定的历史配置明确区分 |
| `deploy/school/` | 可复用的学校部署入口、锁文件和模板 | 不保存实际账号凭据或活跃数据库 |
| `deploy/plans/` | 各次部署、诊断的固定方案、执行脚本与紧凑证据 | 已完成记录保持路径；其内容不能一律当作待执行计划 |
| `docs/` | 当前指南、设计和按日期保留的验收报告 | 当前入口见 `docs/README.md`；历史报告保留当时状态 |
| `data/` | 本机输入、冻结数据及原始材料关联 | 不入 Git；不与生成结果混放或自动合并 |
| `outputs/` | 本机运行、研究、验收和维护产物 | 新任务统一使用此入口，再按用途和运行分组 |
| `output/` | 早期 UI 验收产物 | 历史兼容目录，不再作为新任务输出根目录 |
| `.venvs/`、`models/` | Mac Python 环境、模型与 tokenizer | 保留现有环境名和来源标识，不随实验改名 |
| `logs/`、`.playwright-cli/` | 本机服务日志、浏览器工具记录 | 与应用业务数据、运行证据分别管理 |

WebUI 当前默认把运行状态放在源码树下面。`repos/dataflow-webui/backend/data/`、`cache_local/` 和 `backups/` 都不是可以随意清掉的源码附属文件夹。数据库、受管文件、任务输出和快照存在交叉引用。

## 学校根目录

学校共享根目录为 `/sharedata/home/huruiqian/DataFlow`；`school1` 是管理节点入口，训练与平台容器位于 `node01`。

| 目录或存储 | 实际职责 | 规整原则 |
| --- | --- | --- |
| `app/` | 只读挂入平台容器的代码部署副本，没有独立 `.git` | 与 Mac 源码同步时保留版本和文件清单，不覆盖运行数据 |
| `environments/` | 配置、安装物料、工作脚本和验证记录 | 不是全部 Python 依赖的实际安装位置；训练依赖主要在 Docker 镜像内 |
| `models/` | 基座模型与固定 revision | 保持官方模型名及 revision，不复制到各次运行目录 |
| `offline/` | 可复用的 Linux 离线依赖和来源材料 | 按 Python/Torch/CUDA 目标区分；不与 Mac 环境混用 |
| `runs/` | 论文生成、解析、训练及诊断产物 | 新运行按用途分组；旧目录仍保留实际路径 |
| `platform-data/` | 当前为空，属于早期方案预留目录 | 不将其误标为当前活跃平台数据位置；本轮不删除或启用 |
| node01 的平台状态卷 `/state` | 活跃 SQLite、账号、项目和业务状态 | 保持本地 Docker 卷，不迁到 NFS，不纳入普通 Git 或公开目录清单 |
| node01 的训练缓存卷 `/cache` | Triton 等可重建缓存 | 与模型、最终结果和证据分开；本轮未清理这些卷 |

`environments/platform/` 中的 MinerU 作业、批量上下文和解析容量检查产物目前与运行配置混在一起。这是下一阶段要拆分的内容，不能仅因文件夹叫 environments 就当成环境依赖删除。

## 新名称怎么写

1. 人工建立的目录用小写英文和连字符，运行目录用 `YYYY-MM-DD-用途`。同一天有独立重跑时加 `-r02`；算法版本、代码提交、GPU UUID 和完整参数写进清单。
2. 先按用途分组，再按日期组织运行。例如 `outputs/paper-sft/2026-10-22-batch/`、`outputs/dataflex/2026-10-24-core8-flow-check/`、学校的 `runs/dataflex/2026-10-24-core8-flow-check/`。这些是新路径约定，不表示现有文件已经迁入。
3. 使用 `flow-check`、`capacity-check`、`source-audit`、`evaluation` 等具体用途。通过一次 24 步流程检查的运行，不命名为 `best`、`production` 或算法效果基准。
4. 阶段结构优先用 `config/`、`inputs/`、`logs/`、`outputs/`、`evaluation/`、`evidence/`；仅在自己控制的新运行包中采用。不要改写第三方工具要求的固定布局。
5. 模型名和 revision、`G00`—`G07`、`sample_id`、任务 UUID、`attempt1`、框架 checkpoint 名、自动生成备份名等原有身份保持不变。它们不参加一般文件名美化。
6. 文档使用有意义的连字符名称。当前指南使用稳定名称，如 `workspace-layout.md`；一次检查或验收使用带日期的名称。避免 `final-final`、`new`、`最新版本2` 等会失去含义的名称。
7. GPU 编号和宿主目录不是策略身份。若硬件信息用于区分历史运行，保留原记录；新运行用清单记录实际硬件，避免仅凭 `gpu1` 判断结果用途。

## 旧名称到新名称的迁移清单

以下均为**提案，未执行实体移动或改名**。详细条目及状态见 [rename-plan.json](../deploy/plans/workspace-layout-20261024/rename-plan.json)。

| 当前位置 | 建议的新位置 | 执行前的主要条件 |
| --- | --- | --- |
| Mac `output/` | `outputs/archive/ui/legacy-output/` | 查清旧报告和脚本引用，保留旧路径兼容入口 |
| Mac `outputs/dataflex-core8-20261023/` | `outputs/dataflex/2026-10-23-core8-initial-protocol/` | 标明旧协议，与最终八组分开 |
| Mac `outputs/dataflex-strategy-school-audit-20261023/` | `outputs/dataflex/2026-10-23-school-source-audit/` | 核对代码对照报告中的原始路径 |
| Mac `outputs/paper-batch-20261022/` | `outputs/paper-sft/2026-10-22-batch/` | 保留原始响应、审核记录和来源关联 |
| Mac `outputs/qwen35-9b-8192-env-audit/` | `outputs/environment-checks/2026-10-22-qwen35-9b/` | 保留历史目标 8192 与实际容量结果的区别 |
| Mac `outputs/closeout-20261024/` | `outputs/maintenance/2026-10-24-dataflex-closeout/` | 原清理脚本和回执引用旧路径，需要兼容及映射记录 |
| 学校最新 `gpu1-core8-20261024/` | `runs/dataflex/2026-10-24-core8-flow-check/` | 容器路径、冻结数据链接和证据路径全部核对 |
| 学校 `environments/platform/mineru-bridge/jobs/` | 新解析作业写入 `runs/mineru/<运行>/jobs/` | 先支持独立作业根；既有 worker 路径和归属标识保持有效 |
| 学校 `environments/platform/batch-sft-20261022/` | 新批次使用 `runs/paper-sft/<运行>/` | 分开工作脚本、上下文、缓存和运行状态，核对平台引用 |

`outputs/` 根下零散的 `platform-m*` 文件，适合按历史平台阶段收拢。但实际迁移前必须冻结逐文件映射，不能用一个通配符直接移动或覆盖同名文件。

## 为什么旧目录不能直接批量改名

- 三个保留的训练容器，其 `/runs` 挂载对应宿主的 `runs/qwen35-9b/20261022-smoke/`，并不覆盖整个宿主 `runs/`。将结果移到这个挂载外面，再在旧目录建立宿主绝对路径链接，容器内仍可能无法访问。先验证完整容器路径契约，或只增加指向旧实体的新导航入口，再讨论实体搬迁。
- MinerU 使用解析根目录生成 owner 标识，worker 状态和 engine 路径也依赖原根目录；改名可能影响现有进程的归属验证。目录迁移需要明确的停机、恢复和引用检查，不能靠全局字符串替换。
- Mac 有多个历史脚本直接引用 `backend/cache_local/<任务>/`。WebUI 支持 `DATAFLOW_WORKSPACE_DIR`，但现有开发入口仍有默认路径和团队目录设置；设置一个变量不等于原数据库和所有绝对路径已迁移。
- 历史 JSON、配置和证据中的原路径属于当时记录。保留原内容并增加映射，不把历史记录批量改写成从未使用过的新路径。
- 基座模型、Python 环境、数据库 ID、材料身份、框架输出名和现有压缩快照不参加本次命名迁移。

## 每次运行补什么说明

每个新的运行根目录放一份简短 README 和一份清单，至少记录用途、状态及更新时间、实际实体路径、输入身份、源码版本、环境/模型身份、重跑入口、最终结果和证据位置，以及大文件是否已清理。状态区分“计划”“执行中”“完成”“暂停”“失败”和“已删除大权重但保留证据”；目录存在不代表运行完成。

新增加的索引不改变原始报告。原 SHA-256 清单仍作为其生成时的快照，路径迁移或有意清理另附回执。

## 分批规整顺序

1. 当前阶段：补当前/历史文档入口、目录说明和命名映射，保持服务、挂载、业务数据和证据实体不变。
2. 冻结迁移清单：记录每个实体的旧路径、新路径、引用者、兼容方式和校验方法；优先处理不再运行的 UI 验收产物。
3. 单批迁移：复制并校验，建立兼容入口，再切换少量使用者；同时核对宿主和容器视角。清理旧副本前确认没有独有文件或仍在写入的进程。
4. 应用运行数据和解析桥单独迁移，验证数据库一致性、材料定位、任务重开和缓存可读；不与普通归档改名混做。

当前检查及文档改动见 [2026-10-24 目录检查](maintenance/workspace-directory-audit-20261024.md)。最新 DataFlex 验收及清理状态见 [收尾记录](training/dataflex-closeout-20261024.md)。
