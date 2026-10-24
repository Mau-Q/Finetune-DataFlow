# 文档索引

## 当前使用入口

| 文档 | 内容 |
| --- | --- |
| [安装与启动](getting-started.md) | 克隆、安装、启动、停止与排错 |
| [Windows 开发验收](windows-development.md) | 独立本机开发、自动登录、Windows 启停与实机验收 |
| [Windows 实机验收记录](windows-acceptance.md) | 实际工具和组件版本、修复、离线与浏览器结果、NOT_RUN 边界 |
| [模型 API 配置](model-api.md) | 四类流程的 API 能力、绑定与输出 |
| [架构与组件](architecture.md) | 目录职责、数据路径与运行边界 |
| [目录职责与命名](workspace-layout.md) | Mac/学校存储边界、新目录命名、历史路径兼容及迁移提案 |
| [开发与验证](development.md) | Git、版本固定、回归和发布 |
| [学校部署与操作](school-server-deployment.md) | 当前代码、状态卷、个人 API、解析桥和训练衔接边界 |
| [个人 API 执行](personal-api-execution.md) | Mac/Windows 执行器的职责和连接方式 |
| [Qwen3.5-9B 环境与容量记录](training/qwen35-9b-node01-l40-8192.md) | 2026-10-22 离线安装、短训和容量实测；原目标 8192 OOM，后续变化另见最新记录 |
| [DataFlex 八组流程验证](training/dataflex-gpu1-unified-core8-results-20261024.md) | 真实训练、保存重载、九模型评测及边界；不作为策略排名 |
| [DataFlex 收尾与清理](training/dataflex-closeout-20261024.md) | 已推送版本、最终产物保留、历史大文件清理及容器停止状态 |
| [示例流程](../repos/dataflow-webui/examples/representative-training/README.md) | 示例材料、步骤、逐条隔离与负例重试 |
| [数据备份与恢复](../repos/dataflow-webui/docs/dataset-storage.md) | SQLite 一致性镜像及恢复 |

## 设计与历史证据

[局域网团队协作与数据质检 Spec](lan-collaboration-data-review-spec.md) 记录原始数据集生成关联、项目与账号、单人样本评测及生成数据导出的设计边界；当前实施状态与验证范围见 [实施与验收](lan-implementation.md)。个人开发仍各自运行本机实例，团队共享按专门的 LAN 指南部署。

[DataFlex 接入设计](dataflex-integration-design.md) 与 [分批实施计划](dataflex-implementation-plan.md) 记录模型训练、五类策略配置、固定主机 SSH 及结果展示的新增范围；[B1–B6 交付记录](dataflex-delivery.md) 是 2026-10-20 的离线/隔离验证快照。后续直接 DataFlex GPU 流程已经完成，详见上方八组验证与收尾记录；平台 SSH 训练执行器仍未完成端到端实机验收，两者不混称。

[公开源码整理验证](publication-verification.md) 记录本次回归与安装验证范围。

[全局交互与数据集筛选](interaction-and-dataset-filters.md) 记录编辑保护、公共控件、导入、筛选与统计修复的行为和验收边界。

[WebUI 性能与原生组件布局](performance-and-ui.md) 记录后续首屏精简、请求合并、工具栏与参数面板优化。

[领域术语](../CONTEXT.md)、[v1 范围](finetuning-platform-v1.md)、[实施计划](platform-implementation-plan.md) 和 [ADR](adr/) 保留设计依据。

[M1](platform-m1-delivery.md)、[M2](platform-m2-delivery.md)、[M3–M4](platform-m3-m4-delivery.md)、[M5](platform-m5-delivery.md)、[M6](platform-m6-delivery.md) 与 [数据存储交付](platform-dataset-storage-delivery.md) 是对应阶段的验收记录。它们不代表后来四类代表流程的最新行为；例如 M5 的独立 MM 模板运行拦截与当前 API 图片流程是不同路径，旧的评分/手动收录说明也不能套用到新模板。

[历史安装状态](archive/INSTALLATION_STATUS.md)、[安装调研](archive/INSTALLATION_RESEARCH.md) 和 [论文实验目录](../pipelines/README.md) 保留原始证据，可能含本机路径、旧版本、任务 ID 和旧环境快照。新部署以当前指南及 `locks/components.json` 为准。

DataFlex 与最新主线的关系和验证边界见 [整合记录](dataflex-main-integration.md)。

## 局域网协作交付

- [局域网团队使用](lan-usage.md)：主机初始化、内网 HTTPS、项目与评测。
- [实施与验收](lan-implementation.md)：P0–P5、21 项验收与证据边界。

## 目录维护

- [2026-10-24 目录检查](maintenance/workspace-directory-audit-20261024.md)：实际结构、命名问题、依赖约束与本轮文档补充。
- [首批实际迁移](maintenance/workspace-migration-stage1-20261024.md)：Mac 五项、学校八组结果的实际新实体、旧入口兼容及校验。
- [旧新路径与状态](../deploy/plans/workspace-layout-20261024/rename-plan.json)：六项已迁移、三项延期，明确区分实体目录与入口链接。
