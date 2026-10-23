# DataFlex GPU 2 测试：已确认结果与断网后的本地交付

日期：2026-10-23（Asia/Shanghai）。本地基线为 `72bf9a6`，后续任务改动见本次提交。**真实数据已冻结，短训已有实测结果；八组核心训练、原模型与八个 adapter 的 64 题评测尚未启动。** 学校网络在 18:38 的短超时检查中不可达，此后没有继续连接或修改学校环境。

机器可读状态：[execution-status.json](../../deploy/plans/dataflex-strategy-20261023/execution-status.json)。原验收范围继续采用 [测试方案](dataflex-strategy-test-plan-20261023.md)；本文不把 CPU 检查、训练脚本返回成功或未回读的后台结果当作完整 GPU 验收。

## 已确认的服务器与数据状态

- 连接身份实际核对为 `mgt01/huruiqian` → `node01/huruiqian`。
- 创建专用容器 `rui-dataflex-strategy-gpu2-20261023`，Docker 设备请求实际绑定物理 GPU 2 UUID `GPU-1f7d7941-5155-1c90-819d-5bf7dbec5b18`，network=none；模型只读挂载既有 Qwen3.5-9B revision `c202236235762e1c871ad0ccb60c8ee5ba337b9a`，没有另复制模型。
- 旧 GPU 3 容器保留；创建前只有 sleep，无训练进程。没有停止其他任务。首次新容器因继承 `/bin/bash` entrypoint 而以 126 退出，检查记录留在学校；改用显式 sleep entrypoint 后运行正常。
- 初始安装包的 75 个 Python/默认配置文件与本地逐一同哈希。后续 `base_weighter.py` 的提前释放改动已写入新容器及学校源码，学校 CPU 回归通过；断网后未能再回读其文件哈希。
- SciRIFF 固定 revision 为 `eddf83df1ab4acf1ead5b81898dd4c7e7450050e`，4096 发布配置。用实际 Qwen tokenizer 与 `qwen3_5_nothink` 模板完整编码，冻结 256 训练、32 验证、64 测试，每任务分别 64/8/16。没有翻译、补写、复制或截断样本来凑配额。
- 实际任务为 `scicite_classification`、`genia_ner`、`bioasq_factoid_qa`、`scitldr_aic`。原 `covid_deepset_qa` 在完整序列 ≤1024 后只剩 1/1/2；同属抽取 QA 的 `qasper_extractive_qa` 无可用短样本，因此按已授权范围换用短答案 BioASQ。BioASQ 在 SciRIFF 中属于 `qa.abstractive`，不能称为同一抽取任务。
- 冻结训练集长度 73～1024，监督长度 3～286；验证长度 151～1004，测试长度 93～1023。测试样本始终不进入训练或策略反馈。
- 使用官方划分，并排除完整输入/可提取上下文的已知重复。公开导出没有原论文/文档 ID，不能证明不同上下文没有来自同一篇论文。该限制保留在 manifest 中。

来源及许可依据：[SciRIFF 数据卡](https://huggingface.co/datasets/allenai/SciRIFF)，其任务 provenance 表将 BioASQ、GENIA 标为 CC BY，SciTLDR 标为 Apache 2.0；SciRIFF 自身为 ODC-By。[SciCite 原仓库 LICENSE](https://github.com/allenai/scicite/blob/master/LICENSE) 为 Apache 2.0。数据卡未给出的 CC BY 版本不作推定。冻结 manifest 中 BioASQ 的许可占位文字不再重写，以维持已记录数据身份；这里补充实际查到的许可说明。

## 短训的证据边界

下表是断网前直接读取的结果，所有短训都在实际绑定 GPU 2 的新容器、1024 cutoff、有效 batch 4 下执行。每项为 2 次 optimizer updates。

| 运行 | 实际路径 | PyTorch 峰值分配 / 保留 GiB | 已确认状态 |
| --- | --- | --- | --- |
| GATE-B1 | microbatch 1 / accumulation 4，静态 SFT | 11.260 / 12.045 | 保存 tensor 有限、248 个 LoRA B tensor 非零，步数/loss/真实消费与梯度观察核验完成 |
| GATE-B2 | microbatch 2 / accumulation 2，loss linupper，warmup 0 | 18.391 / 18.609 | 保存、步数、4 个实际加权微批、实际权重导数与 accumulation 缩放核验完成 |
| GATE2-B1 attempt2 | 四任务代表性输入，静态 SFT | 10.986 / 12.045 | 训练及后续 audit 子进程返回 0；重载最终状态未回读 |
| GATE2-B2 attempt1 | 四任务代表性输入，loss linupper | 未回读 | 训练子进程返回 0；最终 resource、audit、重载及 scoring batch1/2 检查未回读 |

初始两个 GATE 实际消费相同 8 条：BioASQ 2 条、SciTLDR 6 条，长度 983～1024，最长答案 35 个监督 token。因此另准备四任务代表性门测，前 8 条包含 1024/1021 长输入、200/286 token 的 GENIA 答案及分类样本。不能仅用初始短答案门测代表完整训练池的加权容量。

初始 B2 的一次驱动层快照为本进程 21,282 MiB；这不是 PyTorch allocated，也不是持续峰值测量。进程 allocator 上限为全卡的 0.42，其他用户占用另计。目前没有高于 1024 的本轮真实数据容量证据。

学校完整原始日志、数据、adapter 均在原独立测试目录；Mac 留存的是明确标为工具观察转录的紧凑 [observed-gates.json](../../deploy/plans/dataflex-strategy-20261023/evidence-20261023/observed-gates.json)，没有伪装成已下载的服务器原始 receipt。初始两次和代表性两次短训共 8 次额外 optimizer updates，不计入尚未执行的 core8 192 步。

## 断网时的后台状态

最后一次观察到的后台命令为 `run_core8_suite.py gates`，当时处于 GATE2-B1 adapter 重载。该命令的 gates 阶段只安排门测与重载，结束后不会自行进入 core 或 evaluate。网络中断不会自动取消服务器上的已启动进程；现在是否完成、是否报错，均待恢复连接后回读。

本轮还启动了只读驱动显存采样器（最多 3600 次、间隔 5 秒）。旧实现的首次尝试因宿主 Python 3.6 不支持 `capture_output` 参数退出，已改为兼容写法并启动第二次采样。完整记录只在学校。恢复后只检查、清理本轮已确认身份的采样进程，不操作其他用户任务。

## Mac 上已完成的工作

1. 增加真实数据准备、代表性门测配置、观察 runner、机制审计、greedy 评测和顺序执行脚本。观察入口记录消费 token 身份、监督/padding、actual backward loss、LoRA 梯度、加权导数、策略计划与打分开销；不会额外调用模型来做训练观察。
2. `base_weighter.py` 在 backward 前释放已被替代的模型输出及其旧 scalar loss 图。CPU 测试同时核对独立公式的 loss、梯度、真实 accumulation 次数，以及原输出对象在 backward 前确实释放。没有声称新 representative B2 的峰值已经降低，因为其 resource 尚未回读。
3. 选择 cache 限定到 attempt；拒绝非空旧 cache。新版配置写到 `execution-v2.yaml` 和 `execution-components-v2.yaml`，保留学校已生成的旧执行配置。
4. core 阶段必须先取得两种四任务门测的 audit、匹配当前 adapter/数据哈希的重载 receipt 和实际 batch1/2 评分一致性证据。阶段分别启动，任何缺失或失败均停止。评测重试可用新的 `--attempt attempt2`，保留旧目录；启动器识别成功评测指针。
5. 评测按任务报告：分类 accuracy/macro F1；NER typed exact entity F1/JSON 成功率；短答案 QA EM/token F1；总结使用明确注明分词方法、无 stemming 的 token LCS ROUGE-L F1。解析失败、空答及 generation cap 均保留并统计，不构造跨任务平均分。总结的事实检查仍待有真实预测后执行。
6. 本地构建 `1.1.0+dataflow.20261023.1` wheel，约 232 KiB，75 个源码/配置文件逐一比对一致，并通过临时解包导入/版本检查。**该新版本尚未上传或安装到学校。** 学校最后已知版本为 `1.1.0+dataflow.20261023`，加本轮手动同步的 graph-release 文件。

本地检查：DataFlex 16 项中 11 通过、5 项因 Mac 无实际 LLaMA-Factory 而跳过；执行配置/阶段保护/评测统计/Delta 重建等 17 项通过；全部任务脚本编译通过，两个宿主脚本另通过 Python 3.6 语法解析。学校断网前的 CPU 回归为 16 项通过、无跳过。以上 CPU 证据不作为八组 GPU 通过结论。

## 空间与恢复执行

约 295 MiB 的本轮 Mac 下载数据在学校五个文件的 SHA-256 全部核验后已删除。构建源临时副本和解包检查目录已自动清理。Mac 只保留代码、紧凑证据、测试日志和尚待上传的 232 KiB wheel。完整训练数据、模型和日志留在学校。

恢复网络后的必要次序：

1. 按连接表重新确认身份、GPU 2 UUID、资源、容器和活动进程；回读 `suite-events.jsonl`、GATE2 audit/resource/evaluation，保留失败尝试。
2. 核对本次提交与学校旧脚本的差异。上传并核验新 wheel/脚本，离线安装后做 source/hash、依赖和 CPU 回归；新 wheel 的小型 Mac 传输副本在学校核验后即可清理。
3. 使用冻结原数据运行 `configure_execution.py --core-only` 生成新的 v2 配置。它会拒绝覆盖已有 v2，不能通过删除历史结果来重试。原数据准备脚本无需重跑。
4. 完成/复核 `gates`。不完整的评测输出保留，必要时为单项重试指定新的 `--attempt`；已有成功输出须匹配当前 adapter 和数据哈希。
5. gates 全部达到原边界后，再依次执行 `core` 和 `evaluate`，核对 8×24 步、配对消费、实际策略与梯度、最终 adapter、64 题预测和人工事实抽查。

八组训练、576 次计划样本级预测、完整结果报告和平台 SSH 训练验收均未完成；当前本地交付仅把可离线完成的实现、检查、安装物料和状态记录准备到可继续执行的程度。
