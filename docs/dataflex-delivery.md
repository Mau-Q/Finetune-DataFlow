# DataFlex B1–B6 离线交付记录

日期：2026-10-20。主要实现位于 DataFlow-WebUI 的 `codex/dataflex-training` 分支。目标是模型训练，策略调整、比较和评测作为配套；独立训练无需实验组。没有连接真实训练主机、安装训练依赖或下载大模型。

## 已实现

| 批次 | 交付 |
| --- | --- |
| B1 | 原生模型训练入口、独立训练 SQLite、方案/可选实验组、数据角色、发布版本绑定、复制、版本冲突与编辑保护 |
| B2 | 静态及 Selection/Mixture/Reweighting/Reorder/Lego；35 个内置组件/预设的源码清单；声明式自定义描述、原生阶段列表、分层检查与专用配置编译 |
| B3 | 数据/媒体/参数文件与源码快照、文件清单哈希、sample_id 来源映射、可搬运包、独立环境预检；固定 HF revision、显式物化的派生包导入；大文件显式引用及远端执行前核验 |
| B4 | 轻量结果导入、幂等/冲突/序号/终态保护、loss/学习率及实际策略信号、失败/缺失状态、条件比较和产物绑定评测 |
| B5 | 单固定主机系统 SSH/SFTP、严格 known_hosts、暂存校验/发布、脱离连接 runner、启动幂等、进程身份/组停止、断线/重连和增量指标/日志同步 |
| B6 | 备份/独立目录恢复、跨批浏览器验收、明暗主题与 390px 窄屏、原有页面及自动回归、使用文档和分仓提交 |

[WebUI 使用说明](../repos/dataflow-webui/docs/model-training.md) 包含主机配置、环境准备、算法扩展、数据映射、HF 准备、运行/结果/评测及备份恢复命令。

## 验证证据

证据分类：TOOL_OBSERVED 为实际工具运行；用户确认单独记录；NOT_RUN 不计为真实运行通过。

| 范围 | 结果与边界 |
| --- | --- |
| 交接 | TOOL_OBSERVED：handoff validator 通过，READ_REQUIRED 七文件在开始实施时记录 SHA-256；当前权威身份另存 evidence |
| 后端训练测试 | TOOL_OBSERVED：训练持久化、API、五类编译、参数/角色约束、哈希/路径、图文发布转换、HF 派生身份（隔离 datasets 替身）、结果、评测、备份恢复、SSH 控制和本地进程测试通过；最终训练测试 23 passed，完整 WebUI 后端 428 passed |
| 隔离 SSH/进程 | TOOL_OBSERVED：命令参数引用与主机验证、上传失败不启动、运行幂等、断线/重连、服务元数据重开、PID 身份不匹配拒绝、真实本地合成子/孙进程组停止、远端发布程序在本地执行、UTF-8 日志偏移重建 |
| 浏览器配置 | TOOL_OBSERVED：无实验组保存/刷新/重开；五类策略逐项保存和编译；Lego 原生阶段列表；高级未知字段保留；自定义描述直接生成 seed 参数表单；方案复制；两个真实浏览器页面 v9/v10 编辑冲突被拒绝 |
| 浏览器结果 | TOOL_OBSERVED：synthetic failed/completed 夹具、曲线、缺失信号、远端产物范围、评测绑定；默认排除夹具，显式包含后显示 strategy/advanced/input identity 差异 |
| 下载 | 用户明确确认“通过”“没有超时”：记录为下载成功。工具的下载事件等待没有作为页面故障结论，也不冒充独立自动化下载证据 |
| 主机未配置 | TOOL_OBSERVED：方案保存与导出可用、启动禁用、明确显示未配置；没有保存或连接虚构主机 |
| 外观与保护 | TOOL_OBSERVED：明暗主题、图表重绘与双轴；390px 窄屏 main clientWidth=scrollWidth=385 无横向溢出；取消导航保留修改，确认放弃后进入原始数据集；已恢复原明亮主题和视口 |
| 旧流程 | TOOL_OBSERVED：原始数据集和生成数据集页面可用；生成/收集/发布/下载等旧契约随完整本地自动测试回归。未在浏览器启动真实外部 API 生成任务 |
| 数据保护 | TOOL_OBSERVED：原数据集 SQLite 逻辑内容不变，90 个原材料文件哈希全部一致。训练备份实际恢复到独立目录，验证 1 个方案、2 个合成运行、1 条评测、2 个运行包；后续浏览器验收新增了一个明确标记的自定义组件方案 |
| 实机 SSH / GPU | NOT_RUN：G1 尚无指定机器/模型/预算，不以隔离测试或合成曲线升级算法运行状态 |

命令及完整输出保存在 `/Users/rui/.codex/handoffs/dataflow/2026-10-20-dataflex-b1-b6/evidence/`，最终记录在 `verification-summary.json`。`./scripts/test-local.sh` 三段为 163 / 428 / 30 passed（另 1 deselected、7 subtests），前端 73 passed、构建通过；diff 检查通过。该目录还包含数据基线备份、文件哈希、独立恢复检查和浏览器截图，未纳入公开仓库。

## G1 与当前能力限制

- 真实 SSH/SFTP 与远端 Linux 行为、CUDA/模型/Tokenizer、数据处理器、逐算法训练和实际停止/断线重连均待资源就绪后验证。文本 SFT 是主线；PT/图文只是源码/离线配置证据，动态 DPO 明确阻止。
- 梯度投影、奖励模型、离线选择文件、MoE 与 DoReMi 参考模型需要各自依赖/资源。配置通过不证明算法语义、依赖或效果通过。
- HF 实际联网下载未执行；隔离替身只证明固定 revision 参数传递、派生身份、重新打包与导入契约。
- 目前适配训练日志和 ODM 权重。其他策略只绘制实际提供的信号，没有信号就显示未提供；不猜测选择样本索引、token 或策略成本。
- 预处理 sample_id 映射未得到准确处理器输出时保持 unknown，不用原始行号冒充。显式外部引用只核验内容哈希，不声称扫描过成员重叠。
- checkpoint 默认保留远端。runner 登记 config/adapter_config 的哈希与身份范围，未把它当作完整模型权重身份、已下载文件或已备份 checkpoint。
- 从头重跑产生新 attempt；checkpoint 恢复、评测调度和自动数据闭环不在当前交付中。runner 身份丢失但子进程退出未确认时显示 unknown，需核对远端记录，不自动判成功或重启。

## 仓库状态

根仓库与 WebUI 各自提交；WebUI 最终提交为 `d8920ba0bfe102e54de9e03d071ec12d01f8b911`（分批历史见实施计划），根仓库锁文件与 gitlink 同步。DataFlex 保持 `2e2a74dbe90f8b6a1394bdee37518980f1d5958d`，没有修改源码或依赖。DataFlow core/MM 保持原版本。

`pipelines/SFT-PIPELINE-OPERATORS.md` 原有删除不属于本任务，保留为未提交状态。所有本任务提交为本地提交，未推送或发布到远端。
