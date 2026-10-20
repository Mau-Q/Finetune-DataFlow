# 文档索引

## 当前使用入口

| 文档 | 内容 |
| --- | --- |
| [安装与启动](getting-started.md) | 克隆、安装、启动、停止与排错 |
| [模型 API 配置](model-api.md) | 四类流程的 API 能力、绑定与输出 |
| [架构与组件](architecture.md) | 目录职责、数据路径与运行边界 |
| [开发与验证](development.md) | Git、版本固定、回归和发布 |
| [示例流程](../repos/dataflow-webui/examples/representative-training/README.md) | 示例材料、步骤、逐条隔离与负例重试 |
| [数据备份与恢复](../repos/dataflow-webui/docs/dataset-storage.md) | SQLite 一致性镜像及恢复 |

## 设计与历史证据

[DataFlex 接入设计](dataflex-integration-design.md) 与 [分批实施计划](dataflex-implementation-plan.md) 记录模型训练、五类策略配置、固定主机 SSH 及结果展示的新增范围；B1–B6 已完成离线/隔离实现与验证，真实 SSH/GPU 训练待 G1 资源就绪后验收。详见 [交付记录](dataflex-delivery.md)。

[公开源码整理验证](publication-verification.md) 记录本次回归与安装验证范围。

[全局交互与数据集筛选](interaction-and-dataset-filters.md) 记录编辑保护、公共控件、导入、筛选与统计修复的行为和验收边界。

[WebUI 性能与原生组件布局](performance-and-ui.md) 记录后续首屏精简、请求合并、工具栏与参数面板优化。

[领域术语](../CONTEXT.md)、[v1 范围](finetuning-platform-v1.md)、[实施计划](platform-implementation-plan.md) 和 [ADR](adr/) 保留设计依据。

[M1](platform-m1-delivery.md)、[M2](platform-m2-delivery.md)、[M3–M4](platform-m3-m4-delivery.md)、[M5](platform-m5-delivery.md)、[M6](platform-m6-delivery.md) 与 [数据存储交付](platform-dataset-storage-delivery.md) 是对应阶段的验收记录。它们不代表后来四类代表流程的最新行为；例如 M5 的独立 MM 模板运行拦截与当前 API 图片流程是不同路径，旧的评分/手动收录说明也不能套用到新模板。

[历史安装状态](archive/INSTALLATION_STATUS.md)、[安装调研](archive/INSTALLATION_RESEARCH.md) 和 [论文实验目录](../pipelines/README.md) 保留原始证据，可能含本机路径、旧版本、任务 ID 和旧环境快照。新部署以当前指南及 `locks/components.json` 为准。
