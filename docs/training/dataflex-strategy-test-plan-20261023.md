# DataFlex 小样本微调策略测试方案

日期：2026-10-23（Asia/Shanghai）。最新执行状态：**真实 256/32/64 数据已冻结，GPU 2 微批 1/2 短训已有实测；四任务门测最终重载/评分结果待校园网恢复后回读，八组核心测试及完整评测尚未启动。** 详见 [执行进度与本地交付](dataflex-core8-progress-20261023.md)。本文后续“未执行”叙述保留原方案制定时的状态，具体当前结论以执行记录及其证据边界为准。先前学校源码核对见 [对照记录](dataflex-school-reconciliation-20261023.md)。

## 1. 目标与验收层次

验证本仓库 DataFlex 在 Qwen3.5-9B 文本 QLoRA 路径中，是否真正执行数据选择、配比、重加权、排序与组合策略，能否保存、重载并完成评测。第一轮优先验证机制，不能依据几十步、单种子、64 条测试的分数给算法排名。

分开记录三个结论：

1. 配置与数学检查通过：不等于真实模型训练通过。
2. GPU 策略机制通过：策略事件、实际数据流及参数更新均有证据。
3. 模型评测完成：原模型和对应 adapter 在冻结测试集上可比较；是否提高能力需另做足量实验。

学校部署文档只记录过静态 SFT 两步、adapter 重载及容量测试，不能作为动态策略已验收的证据。平台训练执行器与容器路径的接入另验，不把直接 CLI 训练成功称作平台端到端成功。

## 2. 本轮源码核对与测试设计影响

核对基线为主仓库 `60e752f`；实际相关文件 SHA-256 与定位见 [source-audit.json](../../deploy/plans/dataflex-strategy-20261023/source-audit.json)。以下是本地代码观察及推断，尚非运行结论。

| 编号 | 源码观察 | 测试设计 |
| --- | --- | --- |
| R01 | `LossWeighter` 对当前微批内样本归一化；单卡微批 1 时最终权重必为 1 | 非均匀加权测试必须微批至少 2；梯度累积不能替代微批大小。微批 1 保留为退化用例 |
| R02 | Select/Mix 的步数由自己的 schedule 推导，mixin 会覆盖 `args.max_steps`；WeightTrainer 不使用这个 mixin | 同时冻结原始配置、trainer 的实际 max_steps、scheduler horizon；不能只检查 YAML |
| R03 | ODM 内部 `warmup_steps` 默认 2000，独立于 trainer 的 `warmup_step`；条件为 `step_id <= warmup_steps` | 首轮分别设内部 0、trainer 4，确认 step 4 已进入动态更新 |
| R04 | standalone MixTrainer 与 Lego 的 ODM batch 回报均使用第一项 domain_id | ODM 正常用例先设微批 1；混域微批归因单独测试，不用微批 2 的混域结果宣称正确 |
| R05 | DoReMi 的 compute_loss 仅在 label_smoother 非空时取出 labels；labels 为 None 的分支直接返回模型 loss | 默认 label smoothing 配置下优先检查是否实际应用域权重；不以比例日志变化代替梯度验证，不为绕过问题开启不合适的 label smoothing |
| R06 | Registry.build 按显式构造参数过滤，未展开 `**kwargs`；ODM 的 reward_scale/min_exploration_rate 通过 kwargs 读取 | 用非默认值检查“配置→实例”的传播；参数被静默忽略应报配置失效，不能宣称覆盖了该参数 |
| R07 | LossSelector 按低/中/高分组改变抽样概率，不是严格选 top-k；默认 preset focus=medium | 验证概率、种子与真实消费 ID；不能要求“所选样本必为 loss 最大的 k 条” |
| R08 | 选择缓存主要按 cache_dir/step 命中；RandomSelector 只记录数量、不保存完整 ID；通用动态 mixin 中未见普通策略状态的完整 checkpoint 恢复契约 | 每次运行独立缓存；实际消费 ID 需要观察钩子。恢复测试必须核对动态状态，adapter 重载与断点续训分开 |
| R09 | 配比管理器按 floor 分配前 K−1 个域，最后一域接收余数，并在域内有放回抽样 | 域数量按确定性取整规则验收；允许有依据的重复，记录不同样本数与重复率 |
| R10 | 编译器输出 max_steps，但不自动输出 train_step；静态混合比例和 mixture_sample_rule 也需要实际绑定到 trainer 使用的 data args | 通过完整编译、实例化及实际 schedule 三层核验；动态路径明确 train_step=24，静态/Weight 路径 max_steps=24 |
| R11 | ReorderTrainer 强制 SequentialSampler；Lego 存在 reorder 时同样采用顺序 sampler | 检查训练实际消费顺序，防止后续 shuffle/按长度分组破坏排序 |
| R12 | README 提到 skills/how_to_use.md 和 examples，但当前 vendored 目录未包含这些入口 | 以后续生成的独立运行配置为准；不得引用不存在的 examples 作为可直接执行的命令 |

上表保留修改前审查的观察。随后用户授权修改本地和学校代码：R05 已改为可微逐样本 CE 加权，不再依赖 label_smoother 是否存在；R06 已修正配置 kwargs 传播且不泄露无关 runtime 对象。R04 对混域微批采用明确拒绝，尚未实现逐域反馈。学校实际安装环境的 13 项 CPU 回归通过；这不代替 Qwen3.5 GPU 训练、完整 DoReMi 参考模型流程或 8 组策略验收。

## 3. 数据方案：352 条真实样本，外加微型可控夹具

首选 [allenai/SciRIFF 4096 配置](https://huggingface.co/datasets/allenai/SciRIFF)，保留英文和原始答案，不调用商业模型翻译、扩写或重新审核。此处 4096 是发布配置名，训练实际采用下述 tokenizer 长度筛选。

| 用途 | 数量 | 分配 |
| --- | ---: | --- |
| 训练候选池 | 256 | 4 个任务来源，各 64 条 |
| 验证 | 32 | 相同 4 个任务来源，各 8 条 |
| 测试 | 64 | 相同 4 个任务来源，各 16 条 |
| 冒烟输入 | 32 | 从训练池各取 8 条，不另增真实样本 |

候选任务：`scicite_classification`（引用分类）、`genia_ner`（实体抽取）、`covid_deepset_qa`（片段抽取问答）、`scitldr_aic`（科研总结）。这 4 个任务类型作为工程配比单元，不称作独立学科域。

准备时必须确认固定 revision 下的任务名、官方 split、过滤后的可用数量和原始文档身份。优先使用官方 train/validation/test；跨 split 仍检查论文/摘要/段落重复。没有可追溯文档 ID 时记录检查能力限制；必要时按来源文档分组重新划分并标注为自定义划分。每任务不够配额时先报告缺口，不复制样本补齐、不静默换题。任务替换需保留相同评分形式并更新 manifest。

首轮按 Qwen3.5 tokenizer 与 `qwen3_5_nothink` 模板筛选完整序列不超过 **1024 token** 的样本；不裁掉问题、关键证据或答案凑长度。每条都要求至少一个有效监督 token，prompt/padding 不参与监督。保存长度分布、监督 token 分布、过滤分母与原因。若某任务不足，先报告后再统一调整预算；微批 2 的显存另行验证，不能沿用微批 1 的历史容量结论。

保存 `sample_id`、原始 instance_id、任务/域、split、来源文档身份、原始及转换内容哈希。元数据置于旁表，不把内部标签插入用户问题。分类保持原标签，JSON 字符串保持可解析，原 input 映射为用户消息、output 映射为 assistant 答案；原格式没有独立 instruction 时不重复拼接。

CPU/小张量测试另用 8～16 个可控 ID、已知分数、不同答案长度、全 mask、非有限分数等夹具。它们只证明实现行为，不能混入真实训练或模型效果评测。

验证集可以供需要目标数据的策略读取，此时必须标注为策略参考集，不能再当独立泛化证据；64 条测试始终不参与选择、配比、锚点刷新或超参调整。

## 4. 统一预算与各策略必要差异

模型/环境沿用 [既有训练方案](qwen35-9b-node01-l40-8192.md)，执行前重新读取实际版本、目标机器身份、GPU 占用与源码哈希。计划值：NF4 4-bit QLoRA、BF16、SDPA、gradient checkpointing、LoRA r16/alpha32、冻结视觉层、packing=false、train_on_prompt=false、非思考模板。

| 参数 | 计划值 |
| --- | --- |
| optimizer updates | 每核心组 24 步；learning rate 2e-5；constant scheduler；LR warmup_steps=0 |
| 总有效 batch | 单卡 4；选择/配比：microbatch=1、gradient_accumulation=4；加权：microbatch=2、accumulation=2 |
| 动态 trainer schedule | warmup_step=4、update_step=5、update_times=4、train_step=24、max_steps=24 |
| 预期动态事件 | global_step 4、9、14、19，共 4 次；先完成该数值步的更新，再为下一步取样 |
| 样本展示次数 | 每组 24×4=96 次；warmup 16 次，每个后续窗口 20 次；不同 ID 总数另计 |
| 组件内部预热 | ODM warmup_steps=0；其他内部 interval 逐项显式设定，不继承长训练默认值 |
| 打分 batch | 默认 1，先确认 logits 与有效标签归一化；再单独测 batch=2 的一致性 |
| 随机性 | seed/data_seed=42；每组独立进程、输出和缓存；关闭 dropout 仅用于数值一致性/重放诊断 |
| 日志/保存/验证 | logging_steps=1；save_steps=12；eval_steps=12；24 步保存最终 adapter |

先跑 32 条、2 个 optimizer updates 的 GATE。它通过后才执行 8 个核心组。24 步低于一次遍历，某些训练样本不被消费是正常现象。相同有效 batch 和步数不等于相同 token、梯度归一化或总算力；必须分别记录 training/scoring/eval token、打分次数与耗时。比较预算遵循 [ADR 0009](../adr/0009-dataflex-comparison-budget-and-source-snapshots.md)。

### 同步调度的具体核验

对 Select/Mix/Reorder/Lego 显式 `train_step=24`，对 Static/Weight 显式 `max_steps=24`；两者均记录原始 max_steps。若经过平台编译，检查实际输出及 advanced.train_step 的传播。这里 warmup_step=4 是 DataFlex 策略预热，不是学习率 warmup_steps。

Mix 绑定四个独立训练文件，固定顺序与 domain_id 映射；`mixture_sample_rule=mixture`，`init_mixture_proportions=[0.25,0.25,0.25,0.25]`。静态混合明确 `static_mix=true`。不能仅设置 component 中的 proportions，就假设已经设置了 manager 的初始比例。

LossSelector 显式 focus=high、focus_weight=5、replacement=false、temperature=1。DeltaLoss 的 update_times=4 需验证首次 baseline 与后续差分分支；不要为了简化设置 update_times=1，使后续轮次计算条件退化。

Loss 重加权使用 `linupper`。`LossWeighter(strategy=uniform)` 仍对归一化 loss 作指数变换，不是等权基线；等权对照使用 `CustomWeighter(strategy=uniform)`。两组必须相同初始权重、微批分组及消费序列。样本均值和 token 均值在答案长度不同时不同，不能要求等权 weighter 与原生标量 token loss 数值恒等。

## 5. P0：训练前必须执行的 10 个检查项目

本表是待执行项目，不是已通过清单。优先用 CPU/小张量和配置编译完成；依赖真实 CUDA 的部分留到 GATE。

| ID | 项目与构造 | 通过标准 |
| --- | --- | --- |
| P00 | 冻结来源、模型、模板、依赖、任务划分与 352 条数据 | revision/哈希可回溯、split/文档无已知交叉、监督非空；缺失身份明确记录 |
| P01 | 配置→编译→注册→实例化；检查 train_type/组件名与各关键参数 | 实际实例属性匹配计划；非法参数或未传播参数失败。`dynamic_weighting` 等错误拼写不能当合法 CLI 类型 |
| P02 | schedule 与实际 trainer/scheduler budget；模拟到 global_step=24 | 24 次更新、4/9/14/19 事件、16+4×20=96 展示预算，无 step24 额外重选 |
| P03 | Random/Loss/DeltaLoss 可控分数及种子 | ID 合法、数量正确、无放回区间不重复；Loss 概率按分组构造可复算；Delta 初始/当前分数与差分方向正确；概率偏好不当作 top-k |
| P04 | 相同样本以 scoring batch1/2 评分；不同答案长度和 mask | 每样本 CE 仅除以其有效监督 token；结果在设定数值容差内一致；全 mask/NaN 明确标记，不作为有效低 loss |
| P05 | 4 域固定配比、偏置配比及 snapshot | uniform 窗口20条为[5,5,5,5]；[.5,.25,.125,.125]为[10,5,2,3]；总数20，域标签正确、有放回重复可追溯 |
| P06 | ODM 已知 batch_loss/domain_id，跨内部预热边界 | reward、平滑、概率与独立公式核对；概率有限非负和为1；内部预热确实结束；混域微批不能错误归因 |
| P07 | 已知 per-sample loss、答案长度和梯度的加权测试 | custom uniform 为样本均值；linupper 权重和为1、数值和梯度吻合；B1退化为1；B2不等 loss 有非均匀权重；梯度累积不重复除法 |
| P08 | 缓存、域顺序与中断状态 | 独立 run 不误读历史step缓存；tokenized snapshot的域顺序/模板/cutoff变化被拒绝；恢复缺少动态状态不能假装无缝继续 |
| P09 | 观察能力与模型评测格式 | 可以捕获真实消费ID/域/标签数/有效权重与实际 backward loss；错误JSON、空答、超限输出保留并计入分母；模型产物哈希绑定评测 |

P01 使用非默认 reward_scale/min_exploration_rate 做传播诊断：修复后的学校 CPU 检查已确认 2.0/0.02 能传入真实 ODM 实例。核心 ODM 首轮仍采用默认 15/0.03；其余参数与配置组合继续按项目核对。

P06 还需记录回报来自哪一个微批：当前 `update_batch_info` 会覆盖上一条信息，边界更新读取最近微批，不是自动聚合整个窗口的域平均 loss。训练步骤返回的 loss 也可能已经过梯度累积归一化。测试要保留原始监督 CE、返回 loss、accumulation 与奖励之间的关系，明确验证的是当前反馈口径；如果预期算法要求窗口聚合，应另列语义差异，不能把该实现当作完整论文复现。

P07 的梯度比较优先使用 FP32 小模型、dropout=0 和等长监督样本，预设 atol=1e-6、rtol=1e-5；再单独覆盖不等长监督的样本均值语义。BF16/QLoRA 重放误差需另定并记录，不能直接套用 FP32 容差或要求权重哈希相等。

## 6. P1：首批 8 组 GPU 核心短训

所有项目当前均为 **NOT_RUN**。按依赖顺序执行，每组从同一原始模型和同种子新建 adapter，不能接着上一组继续训练。

| ID | 模式/组件 | batch / accumulation | 具体验收 |
| --- | --- | --- | --- |
| G00 | static | 1 / 4 | 24步完成；loss/grad有限、LoRA实际改变、基础模型冻结；step12与最终保存；最终adapter重载成功 |
| G01 | dynamic_select / random | 1 / 4 | 4轮重选；每轮20条；记录选择ID及真实消费ID；与重新计算的seed+step结果一致 |
| G02 | dynamic_select / loss(high) | 1 / 4 | 4轮真实模型评分；已知分组概率可核对；ID与打分对应；不能从“loss比随机高”单独判通过 |
| G03 | dynamic_select / delta_loss | 1 / 4 | 保存baseline与后续差分；至少后3轮进入差分选择；数值、窗口和消费映射可追溯，无空窗口崩溃 |
| G04 | dynamic_mix / static_mix | 1 / 4 | 4域初始比例各1/4；96次展示各域24条；标签与来源一致；没有动态更改 |
| G05 | dynamic_mix / odm | 1 / 4 | 4次非预热调用、奖励与domain对应；保存odm_weights.jsonl；每轮20条按新比例重建且真正被消费 |
| G06 | dynamic_weight / custom uniform | 2 / 2 | 同微批内两条，等权样本均值基线；记录有效标签数、loss、梯度及消费顺序 |
| G07 | dynamic_weight / loss linupper | 2 / 2 | step4起应用权重；至少一批不等loss产生非均匀权重；同一批梯度与等权对照有可解释差异；无scalar fallback |

8组共 **192次 optimizer updates**，每组96次样本展示；打分开销另计。GATE 两步及检查/诊断额外预算单独报告，不计入192。G05 首个动态边界有 floor exploration 的情形，首次比例不变可能合理；不要求每次权重必变，而要求输入、计算和应用链路完整，并由 P06 非对称夹具证明变化能力。

G06/G07 以相同 dataloader 消费序列为配对条件；如果序列不同，先修正实验控制，不把不同梯度归因于权重。G00/G06 的 loss 定义可能不同，不用它们直接作数值等价断言。G00 是整体静态基线，G01 是选择策略的调度对照，G04 是 ODM 的固定配比对照。

显存门：先分别测 microbatch1/2；失败保留实际配置和峰值。B2 OOM 时可以从训练池取更短的冻结子集做加权机制诊断，明确变更数据身份；不能退回 B1 后把非均匀加权标为通过。

## 7. P2：排序、组合、恢复与平台接入

核心机制通过后分批执行，不在首批自动铺开全部高开销算法。

| ID | 项目 | 验收要求 |
| --- | --- | --- |
| X00 | 静态 sorting 与 shuffle 对照 | 先用唯一ID/已知score检查完整排列无丢失、重复；再跑24步检查实际消费顺序；保持原始分数→预处理样本的映射，禁止shuffle覆盖排序 |
| X01 | dynamic_folding 或 dynamic_saw，24步 | 4轮重评分；consume_once 在池耗尽前不重用已消费ID，耗尽后的refill另记；相同长度分组不能破坏课程顺序 |
| X02 | Lego select_only 与 G02，24步 | 相同组件/调度/种子/得分输入下，计划预算和合法ID一致；先用固定score诊断比较，再比较真实模型路径，不能只看两次loss相近 |
| X03 | Lego loss filter→reorder，24步 | filter保留50%；下游只操作存活池；每轮最终20条；同一轮共享分数；save_plans=true；不同every下不意外反复缩小旧池 |
| X04 | Lego mix→weight 组合诊断 | 先用均匀/固定mixer与B2权重验证两个空间可组合；ODM+B2混域归因问题解决前标为未支持组合，不作为通过结果 |
| X05 | static 与代表动态策略的 step12 中断→24步 | 对照连续24步；核对optimizer/scheduler/RNG与策略奖励、历史loss、游标、计划、cache状态。若只恢复adapter成功，不能标为断点续训通过 |
| X06 | 平台计划→运行包→真实CLI→结果/评测回读 | 逐一绑定数据/配置/实际源码/依赖/adapter哈希；平台回读步数和策略事件与原日志一致；SSH执行状态单独验收 |

X05 必须使用同一24步scheduler horizon，在step12保存后中断；不能先按12步总预算训练，再把总预算改24来冒充连续运行的恢复对照。若现实现缺失动态状态序列化，应明确失败并规划最小修复，不能静默重新初始化策略。

## 8. P3：梯度、参考模型与特殊模型算法的扩展清单

| 算法 | 先决条件/最小测试 | 当前安排 |
| --- | --- | --- |
| LESS / icons / cluster_less | 核对可选TRAK与投影依赖；32条训练候选+8条策略参考集先检查投影维度、参数名和参考梯度映射，随后再用256条 | 独立执行；不能从Loss选择通过推断梯度选择通过 |
| NICE | 需要真实reward后端、生成与奖励轨迹；多次生成有额外开销 | 本轮不引入新模型或商业API；单独列未测原因 |
| NEAR / TSDS | 真实预计算索引/概率与当前样本顺序和哈希一致 | 用小文件核对合法性，再决定是否做离线计算；随机伪造结果不能当算法验收 |
| DoReMi | 先通过R05的真实梯度检查；核实reference是否成功加载、Qwen3.5模型类与显存；ref/proxy/最终固定配比各阶段的产物可追溯 | 默认缺reference时的fallback不能作为完整DoReMi；不自动加载额外9B模型 |
| adapt / joint_update_aware | 独立策略参考集，B>=2；anchor/target刷新间隔改为短测可触发的值，检查实际隐藏层/标签与梯度 | P1通过后分开测；参考loss不作独立评测 |
| dynamic_moe | 需要有真实gate的MoE模型及其参考集 | 当前Qwen3.5-9B不是本轮MoE测试对象，记NOT_APPLICABLE，不能以不触发gate的运行标通过 |

多卡、DeepSpeed、全参数、DPO、PT、多模态、长序列容量不在本轮正文最小范围；各自需要独立配置和资源测试。

## 9. 评测方案与结果判定

原模型及8组最终adapter用同一64条测试、同一非思考模板、greedy推理、最大新输出256 token；保存原始输出、实际生成长度、stop/上限状态、解析结果和参考答案。不能把上限截断当完整回答。固定4任务，每任务16条，逐任务报告：

- 引用分类：标签准确率、macro F1。
- GENIA NER：按类型实体exact-match F1、JSON格式成功率；失败算入总体分母，另列成功解析子集。
- 抽取问答：遵循该任务原始答案规范的EM/token F1。
- SciTLDR总结：ROUGE-L作复现性检查，并人工抽查关键事实与格式；不以ROUGE替代事实正确性。

这是自定义4任务小测试，**不是官方9个留出任务的完整SciRIFF分数，也不是跨任务泛化结论**。不平均不同指标得到没有定义的总分；32条验证loss仅用于运行观察。此阶段不引入LLM judge，以免新增商业调用变量。

所有完整核心组做64题生成，共原模型64+8×64=576次样本级预测。每组先做8题推理/解析检查，失败则保留错误并暂停全量评测；8题如果配置未变且已保留原始输出可计入64题，不重复生成。测试分数下降不自动判训练工程失败，出现无策略触发、错误归因、伪重加权、产物损坏则失败，即使分数上升。

## 10. 观察产物与执行顺序

每个run独立输出：`manifest.json`、`train.yaml`、`components.yaml`、数据与实际源码哈希、`environment.json`、原始trainer日志、`strategy-events.jsonl`、`consumption.jsonl`、`loss-diagnostics.jsonl`、`resource.json`、checkpoint/adapter文件及哈希、重载记录、原始预测、逐任务metrics、`verdict.json`。

必须在真实dataloader/collator与backward入口观察消费样本、domain、有效标签数及实际加权loss；不能只记录selector声称选中的ID。现有日志不能满足全部字段，执行阶段需先增加可关闭的观察钩子/诊断runner，随后验证观察钩子没有改变正常模型输入、随机流和loss。权重等证据缺失时结论为INCONCLUSIVE，不靠猜测补齐。本轮仅制定计划，未实现观察runner。

源文件中只读到的事实记SOURCE_OBSERVED；数值推断记INFERRED；测试状态用NOT_RUN/PASS/FAIL/INCONCLUSIVE/NOT_APPLICABLE。缺依赖/资源单列原因；修复后产生新attempt，不覆盖失败日志。`source-audit.json` 中列出的状态全部是静态核对，非GPU验收。

执行顺序：P00～P09 → GATE → G00 → G01/G02/G03 → G04/G05 → G06/G07 → 64题评测与汇总 → X00～X06分批 → 按依赖选择P3。任一关键机制失败先定位该类，不让其他类的成功掩盖问题。每次有效样本/源码/配置变化都记录新的身份。

服务器运行时遵守项目连接约定：先读连接表，明确school1/node01目标并确认hostname与账号；实时检查GPU，离线准备物料；不影响其他用户任务。必要依赖和数据由Mac准备再上传，核验后清理本轮可丢弃传输副本。本轮已核实school1/mgt01与node01/huruiqian，按用户后续授权修复并同步学校源码/安装包/测试配置，未启动GPU训练。

用户允许换 GPU，选卡不再固定 index=3。现有训练容器按 GPU UUID 绑定，不能只修改 CUDA_VISIBLE_DEVICES 就访问容器外其他卡；实际换卡需为新测试启动具有目标 UUID 设备绑定的独立容器，或在没有活动训练时重新配置专用容器。任何操作前均刷新显存并保留其他任务。此阶段没有更换 GPU 或重启现有容器。

## 11. 本轮交付与仍需执行的工作

已完成：本地/学校源码与配置对照、352条数据配额、8组核心训练预算、P0/P2/P3项目、必要修复与学校CPU回归、独立配置物化及部署。未完成：实际数据准备、观察runner、GPU短训、完整模型评测和平台SSH训练执行。CPU回归及配置校验不构成各算法完整通过。

机器可读项目见 [test-matrix.json](../../deploy/plans/dataflex-strategy-20261023/test-matrix.json)。配置物化工具为 [materialize_configs.py](../../deploy/plans/dataflex-strategy-20261023/materialize_configs.py)，只生成配置，不下载数据或启动训练。8组配置在学校容器 `/runs/strategy-20261023/G00`～`G07`，数据缺失时仍标记未就绪；该JSON是测试规格，不可直接传给dataflex-cli。
