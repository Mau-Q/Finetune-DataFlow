# 上游来源与许可

本项目在现有开源组件之上提供本地集成和微调数据工作流，不是 OpenDCAI 的官方发行版。

| 组件 | 上游 / 来源 | 许可与处理 |
| --- | --- | --- |
| Core | [OpenDCAI/DataFlow](https://github.com/OpenDCAI/DataFlow)，使用 Mau-Q fork 的修复版本 | Apache-2.0；许可证保留在子模块 |
| WebUI | [OpenDCAI/DataFlow-WebUI](https://github.com/OpenDCAI/DataFlow-WebUI)，使用 Mau-Q fork 的扩展版本 | Apache-2.0；许可证和原作者信息保留在子模块 |
| MM 研究源码 | [OpenDCAI/DataFlow-MM](https://github.com/OpenDCAI/DataFlow-MM) | Apache-2.0；可选子模块，默认不安装 |
| paper-dataflow | 本仓库论文扩展及其 baseline 参考代码 | Apache-2.0；保留扩展 LICENSE 和 vendor manifest |

准确组件提交见 [locks/components.json](locks/components.json)。Core / WebUI 的本地改动由 fork 的 Git 提交记录标识。基线引用来源见 `extensions/paper-dataflow/paper_dataflow/baseline/vendor_manifest.json`。

第三方 Python / JavaScript 包、模型、tokenizer、论文和数据集各有自己的许可与使用条件。源码许可证不授予原始论文、外部数据或模型权重的再分发权。运行数据与模型不随此源码仓库发布。
