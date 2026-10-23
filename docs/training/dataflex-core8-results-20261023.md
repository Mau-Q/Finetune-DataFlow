# DataFlex GPU 2：八组核心运行与冻结评测结果

日期：2026-10-23（Asia/Shanghai）。8 组各完成 24 次 optimizer updates，8 个 adapter 均已保存、重载；原模型与 8 个 adapter 在同一冻结测试集上各生成 64 条预测，共 576 条。选择、配比、实际逐样本权重与梯度链路已有真实 Qwen3.5-9B GPU 证据。**G06/G07 两条独立训练轨迹的梯度归因仍为 INCONCLUSIVE**；同一次前向图的附加诊断确认权重会改变梯度，不能据此宣称两条轨迹已严格匹配。

这是单种子、24 步的小规模工程验收，不能据下表给策略效果排名。直接 DataFlex CLI 路径已执行；平台 SSH 训练执行器、P2/P3 扩展未执行。

机器结果见 [results-summary.json](../../deploy/plans/dataflex-strategy-20261023/evidence-20261023/final/results-summary.json)，全部尝试与额外预算见 [auxiliary-accounting.json](../../deploy/plans/dataflex-strategy-20261023/evidence-20261023/final/auxiliary-accounting.json)。原 [测试方案](dataflex-strategy-test-plan-20261023.md) 与 [断网阶段记录](dataflex-core8-progress-20261023.md) 保留。

## 运行条件与数据身份

- 目标实测为 `mgt01/huruiqian → node01/huruiqian`。专用容器 `rui-dataflex-strategy-gpu2-20261023` 实际绑定物理 GPU 2 UUID `GPU-1f7d7941-5155-1c90-819d-5bf7dbec5b18`，network=none。GPU 2 与原有任务共享；其他用户进程和旧 GPU 3 容器未停止。
- 原有 Qwen3.5-9B 只读挂载，revision `c202236235762e1c871ad0ccb60c8ee5ba337b9a`，没有复制第二份模型。NF4 4-bit、BF16、SDPA、gradient checkpointing、LoRA r16/alpha32/dropout 0.05、packing=false、train_on_prompt=false。实际依赖版本及 tokenizer/LF 文件哈希见 [runtime-provenance.json](../../deploy/plans/dataflex-strategy-20261023/evidence-20261023/final/runtime-provenance.json)。
- DataFlex 安装版本 `1.1.0+dataflow.20261023.1`；安装包及学校平台目录的 75 个源码/默认配置文件与本地部署基线 `4070b69` 比对一致。各运行另保存实际源码哈希；观察与评测脚本在恢复执行时修复，不能把基线 commit 当成所有后续脚本的执行身份。
- SciRIFF revision `eddf83df1ab4acf1ead5b81898dd4c7e7450050e`，4096 发布配置；完整 LF 编码 ≤1024，无裁断凑额。冻结 256 train / 32 validation / 64 test，四任务各 64/8/16。数据 manifest SHA-256 为 `f2e723257b323c022729a01207b45c036d3c98d61debdc71087a252e58c66b7e`，恢复后未重新抽样。
- 四任务为 SciCite、GENIA、BioASQ、SciTLDR。原 covid_deepset_qa 过滤后仅 1/1/2；qasper_extractive_qa 为零，因此改用 BioASQ 短答案 QA。它在 SciRIFF 属于 qa.abstractive，评分仍用 EM/token F1。公开导出缺原文档 ID；已排除可识别的完整输入/上下文重复，不能证明同论文不同上下文无交叉。
- 测试集不进入选择或配比反馈。训练观察实际核验 token 身份、prompt/answer mask、padding、有效监督数、optimizer 步与代表性 LoRA 梯度；八组最终 adapter 的 tensor 均核验有限，LoRA B 有实际变化。

## 1024 token 容量门测

每门测 2 次更新、有效 batch 4。初始 B1/B2 用长输入短答案；代表性 B1/B2 另覆盖四任务、最长 1024 输入及 286 个监督 token。

| 门测 | 微批 / 累积 | allocated / reserved GiB | 结果 |
|---|---:|---:|---|
| GATE-B1 | 1 / 4 | 11.260 / 12.045 | 保存与机制核验通过 |
| GATE-B2 | 2 / 2 | 18.391 / 18.609 | 非均匀加权、保存与梯度缩放核验通过 |
| GATE2-B1 | 1 / 4 | 10.986 / 12.045 | 四任务代表性训练与修正后的非思考重载通过 |
| GATE2-B2 | 2 / 2 | 16.192 / 17.926 | 同上，实际 scoring batch1/2 一致性通过 |

本轮已观察到 1024、microbatch 1/2 可以完成；这不保证之后其他任务增加占用或更长序列仍有空间。scoring batch1/2 的实际 loss 最大差约 0.01197，使用预先记录的 atol=0.03、rtol=0.01。

## 实际训练与策略证据

每组 24 步、96 次样本展示。下表来源顺序为 BioASQ / GENIA / SciCite / SciTLDR；重复率是 `1−不同样本数/96`。CLI 时间含加载、训练、评分、保存与验证，scoring 秒数是其中的子集，不能再与 CLI 相加。

| 组 / 策略 | attempt | 不同样本 / 重复率 | 四来源次数 | 有效 / 监督 token | CLI / scoring 秒 | allocated / reserved GiB |
|---|---|---:|---|---:|---:|---:|
| G00 static | attempt1 | 96 / 0.0% | 19/18/30/29 | 46963 / 3776 | 176.5 / 0.0 | 11.212 / 12.076 |
| G01 random select | attempt1 | 80 / 16.7% | 27/29/20/20 | 46919 / 4605 | 175.1 / 0.0 | 11.309 / 12.035 |
| G02 loss(high) select | attempt1 | 79 / 17.7% | 28/17/15/36 | 51626 / 3181 | 471.9 / 284.4 | 11.335 / 12.211 |
| G03 delta loss select | attempt1 | 79 / 17.7% | 15/45/21/15 | 48740 / 6523 | 488.3 / 304.2 | 11.335 / 12.217 |
| G04 static mix | attempt1 | 81 / 15.6% | 24/24/24/24 | 47996 / 3928 | 178.8 / 0.0 | 11.260 / 11.998 |
| G05 ODM mix | attempt1 | 78 / 18.8% | 21/21/27/27 | 47245 / 3736 | 176.7 / 0.0 | 11.333 / 12.215 |
| G06 uniform weight | attempt4 | 96 / 0.0% | 19/18/30/29 | 46963 / 3776 | 173.7 / 0.0 | 16.366 / 17.572 |
| G07 loss linupper | attempt2 | 96 / 0.0% | 19/18/30/29 | 46963 / 3776 | 178.0 / 0.0 | 16.366 / 17.572 |

- G01/G02/G03 在 step 4/9/14/19 重选，每轮 20 条；实际消费 ID 与计划完全对应。随机种子、loss(high) 分组概率、Delta 基线和后续窗口均独立重建核对。Delta 后三次窗口为 [32,83]、[172,223]、[203,254]。
- G04 四来源各 24 次，按固定比例实际消费；G05 四次 ODM 回报、更新公式与取整后的域数量均匹配。**当前 ODM 回报采用上一微批返回的、经累积缩放的 loss，不是整窗口/整个域的平均 loss。** 本轮只验该实际实现，不扩张为理想化 ODM 语义。
- G06/G07 各有 40 个实际加权微批；等权为 [0.5,0.5]，linupper 在不等 loss 的两样本批次约为 [0.269,0.731]（次序依 loss）。反传到逐样本 loss 的系数分别为权重/2，符合 accumulation=2，无 scalar fallback。两样本 min-max 归一化会把权重幅度压成固定的这两档，不能称其幅度随原始 loss 差值连续变化。

## 加权配对的未解决限制

初次 G06/G07 的消费序列相同，但预热梯度已经不同，原配对归因不成立。保留 attempt1，另外使用完全相同的全量 LoRA 初始快照（tensor SHA-256 `3bf6a156850eca6cc0a5a0f914ed9eae38002687fc94f6ec585a1dbcd321820f`），每微批显式设 CPU/CUDA seed=420000+micro，并记录相同 CUDA RNG 哈希。这个步骤是实验控制，不能称为被动观察。

补跑 G06 attempt4 / G07 attempt2 的初始状态、消费批次和所记录 RNG 相同，但预热代表性梯度仍有值超过事先声明的 atol=1e-4、rtol=0.02。严格审计因此失败，未放宽容差，也未将完整轨迹差异归因于权重；根因尚未确认。

随后以实际 micro9 的同两条训练样本、同一初始 adapter，进行一次 Qwen 前向，在同一份可微 loss 图上分别计算 uniform 与 linupper 梯度，另重复 uniform 检验。该诊断没有 optimizer 更新；只隔离“权重是否改变梯度”这一问题。

| 代表性参数 | 等权梯度范数 | linupper 梯度范数 | 等权重复 L2 差 | 权重造成相对 L2 差 |
|---|---:|---:|---:|---:|
| LoRA A | 0 | 0 | 0 | 0.000% |
| LoRA B | 7.45693 | 5.20736 | 0 | 43.746% |

同图诊断通过意味着实际加权函数会改变该批 LoRA 梯度。它不补成跨进程轨迹可复现性证据。严格失败日志与诊断 receipt 均保留，机器汇总的 `inconclusive` 明确记录这一限制。

## 冻结测试集结果

所有 9 组使用同一原生 HF chat template，enable_thinking=false，greedy、max_new_tokens=256。每任务 16 条。分类/QA 严格使用原答案；NER 无效 JSON 作为空预测保留全部真值的 FN，解析失败不从分母移除。没有跨任务总分。

| 模型 | SciCite Acc / macro F1 % | GENIA micro F1 / JSON % | QA EM / token F1 % | TLDR ROUGE-L F1 % | cap / 空答 / think | 评测秒 |
|---|---:|---:|---:|---:|---:|---:|
| BASE | 75.00 / 77.27 | 29.71 / 87.50 | 25.00 / 58.26 | 22.21 | 2 / 0 / 0 | 179.0 |
| G00 | 81.25 / 76.00 | 27.96 / 100.00 | 37.50 / 56.01 | 27.17 | 0 / 0 / 0 | 198.2 |
| G01 | 81.25 / 76.00 | 28.79 / 93.75 | 43.75 / 56.37 | 25.97 | 1 / 0 / 0 | 197.4 |
| G02 | 87.50 / 53.17 | 27.82 / 100.00 | 43.75 / 58.10 | 28.10 | 0 / 0 / 0 | 214.5 |
| G03 | 81.25 / 76.00 | 29.45 / 100.00 | 43.75 / 58.10 | 26.83 | 0 / 0 / 0 | 213.1 |
| G04 | 81.25 / 76.00 | 29.86 / 100.00 | 43.75 / 56.37 | 27.49 | 0 / 0 / 0 | 210.7 |
| G05 | 87.50 / 80.77 | 31.13 / 100.00 | 43.75 / 58.10 | 26.38 | 0 / 0 / 0 | 185.7 |
| G06 | 81.25 / 76.00 | 30.48 / 100.00 | 37.50 / 56.01 | 26.02 | 0 / 0 / 0 | 201.7 |
| G07 | 81.25 / 76.00 | 28.14 / 93.75 | 37.50 / 56.01 | 26.79 | 1 / 0 / 0 | 188.7 |

分类测试分布 Background=13、Method=1、Result=2；恒猜 Background 的 accuracy 即 81.25%，因此高 accuracy 不等于三类都学好。GENIA 测试有一条参考答案本身 311 个监督 token，超过统一 256 生成预算；cap 和失败仍按原分母报告，不事后换题或调预算。QA 用单条 SciRIFF 公开参考，没有补充官方隐藏别名。TLDR 是小写 Unicode 词/标点分词、无 stemming 的 token LCS F1，不伪称完整官方评测。

人工事实检查固定取前两个冻结 SciTLDR ID（test:76、test:481），逐一对照原输入与九组输出；范围仅 18 条摘要，不代表全部事实可靠性。具体记录见 [manual-review.json](../../deploy/plans/dataflex-strategy-20261023/evidence-20261023/final/manual-review.json)。

样例 76 的八个 adapter 输出均把训练优化目标扩大为已取得训练加速，而给定输入只列推理/批量预测测速，故标为证据范围扩大；BASE 的主贡献表述吻合，也不能当作训练测速的独立证据。样例 481 的九条主贡献表述均得到给定输入支持。这里核对的是输入对输出陈述的支持程度，没有外部核查论文全部实验。

## 失败、修复与预算

- 最初用 LF encode_oneturn 的训练 prompt 直接做生成，实际输出了 `<think>` 并顶到 256 cap。此模板名不能保证生成时非思考；正式评测改用原生 tokenizer 的 enable_thinking=false 空思考前缀，检查原始生成 token 中没有思考标签。旧四条错误模式门测预测保留。中间一次 HF 新接口返回 Encoding 而非 ID 列表，在生成前报错；改为先模板文本再 encode。
- 加权配对回调的两次初版因同名变量遮蔽 TrainerControl / TrainerState 在 0 更新时报错；保留 G06 attempt2/3。其后用实际 PEFT 的 CPU 回调测试覆盖状态/控制对象及全量初始权重恢复。共享快照在 0 更新处保存，后续两组均只读恢复。
- 同图诊断初版误用了 per-sample loss 的默认 detach，反传前失败、0 更新；attempt2 显式 detach=False 后执行。首次容器 entrypoint、宿主 Python3.6 subprocess 参数兼容等准备错误，也保留原始日志。
- 核心训练实际消费 383,415 个有效 token，其中 33,301 个监督 token；选择评分另有 991,656 个有效 token。各组有两次 schedule 验证及一次 CLI 最终验证；每组验证 token 预算 48,249 是按完整循环和冻结长度推导，未伪称为 collator 直接观测。
- 接受的 core8 共 192 更新、768 次展示。另有旧 G06/G07 48 更新及四门测 8 更新；因此全部实际观察为 **248 更新、992 次训练展示**。加权配对失败后的两组补跑被用作最终 adapter；原两组计额外开销。
- 正式预测 576 条，门测额外 8 条（4 条旧错误模式、4 条修正模式）；评分和同图诊断不做 optimizer 更新。G02/G03 共 2048 次样本评分前向；门测 batch 一致性两次共 16 次样本前向；同图诊断两次各 2 条（失败与成功均计）。实际评分 token 与秒数在 JSON 中单列。
- 八组 checkpoint-12、checkpoint-24、最终 adapter 均在学校保留。save_only_model=true；此轮验证保存/重载，不宣称 optimizer、RNG、动态策略状态可完整断点续训。

核心 CLI 合计 2019.1 秒（含 scoring 588.6 秒），正式 9 组评测 1789.0 秒；成功的同图诊断另用 128.6 秒。部署排障、失败诊断与额外训练不包含在核心 CLI 合计中，该合计不是整轮工作的总墙钟时间。显存表为单进程 PyTorch allocated/reserved；采样期间每 5 秒记录的整卡峰值 43821 MiB、最低空闲 1553 MiB 包含其他任务，不能混称为本进程连续峰值。

## 留存与验证

完整数据、原始预测、选择/梯度轨迹、所有尝试、adapter、checkpoint 在学校 `/sharedata/home/huruiqian/DataFlow/runs/qwen35-9b/20261022-smoke/strategy-20261023`；脚本/日志在 `/sharedata/home/huruiqian/DataFlow/environments/qwen35-9b/strategy-20261023`。运行目录实测 7.3G（包含保留的额外尝试）。容器 writable layer 约 1.69 MB；镜像快照顶部新增层标示 2.16 GB。原模型只读复用，镜像 virtual 总大小不能当成新增占用；未单独测量 Docker 的去重后物理增量。

本轮 Mac 临时数据下载约 295 MiB、wheel/传输压缩包在学校 SHA-256 核验后已删除；Mac 仅保留源码、紧凑证据和两个必要人工检查例子。未删除原有模型、数据、项目和他人任务。

最终回读确认两个容器仍运行，测试容器只有 sleep；GPU 2 空闲显存回到约 22,442 MiB。初次清理因采样脚本实际名为 `driver-monitor.py` 而未匹配，核对 PID、完整命令与脚本内容后已停止本轮自己的 PID 17225。最终机器状态与清理动作见 [final-state.json](../../deploy/plans/dataflex-strategy-20261023/evidence-20261023/final/final-state.json)。

验证：Mac 执行工具 21 项中 20 通过、1 项因未安装实际 PEFT 跳过；DataFlex 16 项中 11 通过、5 项因无实际 LF 跳过。学校对应 21 项及 DataFlex 16 项全部通过、无跳过。任务脚本编译与宿主 Python3.6 语法检查通过；未运行整个 DataFlow/WebUI 回归，因为本次后续修改限独立实验脚本。Git 保留用户原有 `pipelines/SFT-PIPELINE-OPERATORS.md` 删除，未纳入任务提交。
