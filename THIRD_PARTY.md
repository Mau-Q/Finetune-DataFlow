# 上游来源与许可

本项目在现有开源组件之上提供本地集成和微调数据工作流，不是 OpenDCAI 的官方发行版。

| 组件 | 上游 / 来源 | 许可与处理 |
| --- | --- | --- |
| Core | [OpenDCAI/DataFlow](https://github.com/OpenDCAI/DataFlow)，集成 Mau-Q fork 的修复版本 | Apache-2.0；许可证保留在源码目录 |
| WebUI | [OpenDCAI/DataFlow-WebUI](https://github.com/OpenDCAI/DataFlow-WebUI)，集成 Mau-Q fork 的扩展版本 | Apache-2.0；许可证和原作者信息保留在源码目录 |
| DataFlex | [OpenDCAI/DataFlex](https://github.com/OpenDCAI/DataFlex) | Apache-2.0；集成训练源码、依赖声明及上游说明，保留 LICENSE 和 UPSTREAM.json；不包含上游演示数据及工作流 |
| MM 研究源码 | [OpenDCAI/DataFlow-MM](https://github.com/OpenDCAI/DataFlow-MM) | Apache-2.0；可选子模块，默认不安装 |
| paper-dataflow | 本仓库论文扩展及其 baseline 参考代码 | Apache-2.0；保留扩展 LICENSE 和 vendor manifest |

准确组件提交见 [locks/components.json](locks/components.json)。Core / WebUI / DataFlex 的导入提交与原始文件哈希保存在各自的 `UPSTREAM.json`；后续改动由本仓库的 Git 历史标识。基线引用来源见 `extensions/paper-dataflow/paper_dataflow/baseline/vendor_manifest.json`。

第三方 Python / JavaScript 包、模型、tokenizer、论文和数据集各有自己的许可与使用条件。源码许可证不授予原始论文、外部数据或模型权重的再分发权。运行数据与模型不随此源码仓库发布。
