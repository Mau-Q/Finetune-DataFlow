# 论文 SFT Pipeline：正选与备选算子开发说明

核对日期：2026-09-26。

本文整理本次讨论中的主流程算子和备选算子，共 24 个不同的算子。`PandasOperator` 在主流程中使用两次，合并介绍；此前统称的 Deita、RM、Superfiltering Filter 分别展开。

源码依据：本地 `repos/dataflow`，提交 `d70f9ef30a7da5dc9f0684c9abc3ec90d8332313`；核对时该仓库工作区无修改。文中的实现细节对应这一版本，不保证与未来版本相同。各条目附相对于本文的源码链接。

**“正选”表示此前提出的主流程候选，不表示已经验证为最优。** 当前约束是使用官方算子和官方提示词，可配置模型、字段、官方语言模板和筛选参数；这份文档不代表已运行或验收完整流程。中文适用性、阈值效果和训练收益仍需实验验证。

## 阅读与接入约定

每个条目按“作用与机制 → 输入与输出 → 使用场景 → 关键限制”展开。示例用于解释行为，未标记为实验结果。

- **数据与返回值**：算子通过 Storage 读写表格；`run()` 的返回值可能是字段名或其他信息，不能统一当作处理后的数据表。
- **来源与中间结果**：保留论文标识、原始材料和生成候选；需要比较过滤效果时保存过滤前的评分表。去重不会自动合并来源，若需要多来源关系，应在去重前建立对应表。
- **评价结果的含义**：评分、独立质量审核与训练收益分别验证。当前中文适用性和阈值效果的实验状态统一见文首，各算子只列出直接影响使用的特殊边界。
- **导出目标**：依据“给定上下文回答”或“问题可独立回答”的训练目标决定 `input` 内容，审核证据与训练输入分别配置。

## 一、流程与算子位置

```text
文档路径或 URL
  ↓ FileOrURLToMarkdownConverterFlash 等文档转换方案
Markdown 文件路径
  ↓ KBCChunkGenerator
原文片段 raw_chunk
  ↓ KBCTextCleaner
清洗副本 cleaned_chunk，同时保留 raw_chunk
  ↓ Text2MultiHopQAGenerator
嵌套问答列表 QA_pairs
  ↓ PandasOperator：展开列表并保留来源
独立 QA 记录
  ↓ Text2QASampleEvaluator
四维分数与反馈
  ↓ AlpagasusSampleEvaluator：将原文映射到 input
整体质量分数
  ↓ GeneralFilter
满足条件的记录
  ↓ HashDeduplicateFilter
精确去重后的记录
  ↓ PandasOperator：整理训练字段
SFT 数据
```

| 环节 | 正选 | 备选或补充分支 |
|---|---|---|
| 文档转换 | `FileOrURLToMarkdownConverterFlash` 为此前举例的实现 | 已有可靠 Markdown 时跳过转换；实际后端须匹配环境 |
| 分块、清洗 | `KBCChunkGenerator`、`KBCTextCleaner` | 本次未确定其他替代算子 |
| 生成 | `Text2MultiHopQAGenerator` | `Text2QAGenerator`、`SFTGeneratorSeed` |
| 改写 | 主流程暂不设置 | `CondorRefiner` |
| 评价 | `Text2QASampleEvaluator`、`AlpagasusSampleEvaluator` | Deita Quality、Deita Complexity、RM、Superfiltering 评价器 |
| 筛选 | 先评价，再用 `GeneralFilter` | 五种对应的专用 Filter |
| 去重 | `HashDeduplicateFilter` | `MinHashDeduplicateFilter`、`SemDeduplicateFilter` |
| 表格整理 | `PandasOperator` | 用于展开和导出 |
| 通用指令合成 | 不在论文主流程中 | `CondorGenerator`，作为边界说明 |

## 二、正选算子

### 1. FileOrURLToMarkdownConverterFlash

**作用与机制**

文档转换是论文处理的入口。这个算子识别输入的本地路径或 URL，将不同形式的文档统一到 Markdown 文件，供后续分块算子读取。它负责文档内容抽取和文件落盘，不承担问答生成。

对于 PDF 和图片，算子调用 FlashMinerU 批量解析，并把解析结果对应回原始记录；对于网页等输入，使用对应的正文抽取路径。输出表保留文件入口，使后续流程可以围绕同一种文本文件接口工作。

**输入与输出**

`source`（路径或 URL）→ `text_path`（Markdown 文件路径）。下一步用 `KBCChunkGenerator` 打开该文件。

**使用场景**

适合原始材料包含 PDF、图片或网页的情况。如果已经有经过检查的 Markdown，可以直接从分块开始。

**关键限制**

- Flash 版本初始化需要 FlashMinerU、模型文件和相应 GPU 环境；选用前需要确认执行后端。
- 解析结果不自动提供完整的页码与字符级追溯；需要这类来源信息时，应保留解析器的相关产物。

[源码](../repos/dataflow/dataflow/operators/knowledge_cleaning/generate/mineru_operators.py)

### 2. KBCChunkGenerator

**作用与机制**

这个算子把整篇文档转换成可独立处理的片段，让清洗和问答生成围绕局部材料执行。它从输入列取得文本文件路径，读取正文，再按照所选切分策略生成多个 chunk。

可配置项包括切分方式、块大小、重叠长度和最小块长度。重叠用于把边界附近的上下文带入相邻片段。当前实现为每个片段复制原记录的其他字段，因此一篇带有论文 ID 的文档，可以展开成多行仍携带该 ID 的记录。

**输入与输出**

`text_path` → 多行 `raw_chunk`。原始文档记录被展开，已有的其他字段随片段复制。

**使用场景**

适合把长论文接入逐片段处理。例如，一篇文档切成十个片段后，清洗器分别处理十行数据，生成器再从各片段构造问答。

**关键限制**

- 切分不保证形成完整知识单元；应检查公式与解释、结论与条件是否被拆开。
- 块大小的计量与具体切分策略有关；当前长文本还存在预切分路径，参数应结合实际输出确认。

[源码](../repos/dataflow/dataflow/operators/knowledge_cleaning/generate/kbc_chunk_generator.py)

### 3. KBCTextCleaner

**作用与机制**

这个算子在原始片段与问答生成器之间增加文本清洗步骤。它为每条片段组织清洗提示词，调用配置的模型服务，再提取模型返回的清洗正文，写入新的结果列。

采用独立输出列时，下游生成器可以读取更便于处理的清洗副本，同时原始片段仍可用于来源核对。这个安排让文本加工和原文保存各自有明确位置，也方便比较清洗前后的差异。

**输入与输出**

`raw_chunk` → 新增 `cleaned_chunk`，保留原列和其他记录字段。

**使用场景**

适合文档抽取后存在断行、杂乱表达等问题的材料。主流程让生成器读取 `cleaned_chunk`，让带证据评价环节读取 `raw_chunk`。

**关键限制**

- 这是模型驱动的改写，可能改变数字、公式或限定条件；需要原文核对的任务应使用独立输出列，保留清洗前材料。

[源码](../repos/dataflow/dataflow/operators/knowledge_cleaning/generate/kbc_text_cleaner.py)

### 4. Text2MultiHopQAGenerator

**作用与机制**

这个算子用于生成需要联系多个事实才能回答的问题，适合机制关系、步骤衔接和综合解释类训练样本。相对于直接询问一个名称或数值，它试图让答案说明事实之间的关系。

当前实现先按语言配置分句，将相邻三个句子组织为前提、中间信息和结论，并选取补充上下文，再调用模型生成结构化问答。预期内容包含问题、答案、推理步骤和支持事实。生成结果解析为列表后写回当前片段记录，没有生成有效 QA 列表的记录会被移除。

**输入与输出**

`cleaned_chunk` → `QA_pairs` 列表与 `QA_metadata`。每个保留的片段可以带有多条 QA，下一步需要展开列表。

**使用场景**

例如，材料分别说明“检索产生候选”“重排序选择段落”“生成器读取最终段落”，可以据此构造“为什么未被检索到的材料无法通过重排序进入生成上下文”的综合问题。

**关键限制**

- 相邻句子未必存在推理关系；分句语言配置和片段长度会直接影响候选构造。
- `supporting_facts` 是生成内容，不是已经核验的引文。需要证据审核时仍应回到原文。
- 不同解析路径的字段检查不完全一致；展开 QA 前应检查下游所需字段是否齐全。

[源码](../repos/dataflow/dataflow/operators/core_text/generate/text2multihopqa_generator.py)

### 5. PandasOperator

**作用与机制**

这个算子把常见的数据表加工接入统一的 Storage 流程。它按顺序执行配置的函数，每个函数接收 DataFrame 并返回新的 DataFrame，随后将最终表格写回。它本身不调用模型。

主流程中有两次用途。第一次把 `QA_pairs` 列表展开为一行一条问答，并将问题、答案、原文和论文信息放到对应列。第二次在筛选与去重之后重命名或选择字段，形成训练程序需要的结构。

**输入与输出**

DataFrame → 转换后的 DataFrame。列名、列数和行数由所配置的函数决定。

**使用场景**

一个片段包含三个 QA 时，可展开成三行，每行复制同一片段的来源信息；导出时再将 `question/answer` 映射成 `instruction/output`。

**关键限制**

- 必须提供具体转换函数，并保证每步返回 DataFrame；没有自动识别任意 QA 结构的功能。
- 展开时的来源对应关系由处理函数负责，不能只展开答案而丢失原文关联。

[源码](../repos/dataflow/dataflow/operators/core_text/refine/pandas_operator.py)

### 6. Text2QASampleEvaluator

**作用与机制**

这个评价器把 QA 的整体观感拆成四项可分别观察的指标：问题质量、回答对齐、回答可验证性和下游价值。它为每个维度构造对应提示词，分别提交模型服务，并从回复中解析评分与反馈。

这种设计适合诊断质量问题来自哪里。例如，一条样本可能问题清晰、答案也切题，但下游价值较低；另一条可能问题有价值，答案却没有充分回应。保存各维度结果后，可以比较不同筛选规则，而不必重新生成 QA。

**输入与输出**

问题列＋答案列 → 新增四类分数和四类反馈，保留待评价记录。

**使用场景**

放在生成与表格展开之后、筛选之前。需要分析拒绝原因时，可同时查看低分维度及对应反馈。

**关键限制**

- 当前模型输入只有问题和答案，不读取原文；“可验证性”评分不能作为已完成论文事实核验的标记。
- 评分格式未匹配时返回零分；处理低分时需要区分评价结果与解析失败。

[源码](../repos/dataflow/dataflow/operators/core_text/eval/text2qa_sample_evaluator.py)

### 7. AlpagasusSampleEvaluator

**作用与机制**

这个评价器将指令、输入材料和回答共同组织成评价请求，让模型按指定维度给出整体分数。默认维度为 `quality`，官方提示词要求使用 0～5 分，并附带解释。

在论文流程中，将问题映射为 instruction、清洗前片段映射为 input、答案映射为 output。这样可以补充仅查看 QA 的评价器，让评分模型依据同一条记录中的材料评价回答。当前代码提取回复首行的数值并写入评分列，后续可排序或设置保留区间。

**输入与输出**

问题＋原始片段＋答案 → 新增 `AlpagasusScore`，记录数量不变。

**使用场景**

适合在已有来源材料的指令任务中进行整体评分。在本流程中，它与 Text2QA 的分维度评价提供不同角度的观察。

**关键限制**

- 官方提示词是整体评价，没有专门的逐事实支持判定协议。
- 当前只保存分数，不保存模型生成的解释；分数解析要求回复首行具有预定数字格式。

[源码](../repos/dataflow/dataflow/operators/text_sft/eval/alpagasus_sample_evaluator.py)

### 8. GeneralFilter

**作用与机制**

这个算子将已经确定的选择条件应用到数据表。每条规则接收整个 DataFrame，并返回与其索引对应的布尔 Series；算子将所有规则用 AND 合并，只保留每条规则均为真的行。

它可以同时使用多个评分列和普通字段。例如，要求问题质量达到阈值、回答对齐达到阈值，并且答案字段非空。由于评价与筛选分离，更换规则时可以直接复用已经保存的评分数据，无须再次调用模型。

**输入与输出**

包含所需字段的数据表 → 满足所有规则的记录；不会重新计算模型评分。

**使用场景**

适合仍在比较阈值的开发阶段，也适合组合多个评价器的结果。数值阈值、字段合法性等条件可以集中表达。

**关键限制**

- 规则必须返回布尔 Series，且应与输入表索引对齐。
- 当前输出仅含保留行，不自动生成逐条拒绝原因；需要拒绝分析时应保留过滤前的表格。

[源码](../repos/dataflow/dataflow/operators/core_text/filter/general_filter.py)

### 9. HashDeduplicateFilter

**作用与机制**

这个算子用于消除指定文本内容完全相同的记录。它从一个字段读取文本，或将多个字段按固定方式组合，再计算哈希；遍历时保留首次出现的内容，对已出现的内容标记为重复并过滤。

开发者通过字段选择定义去重粒度。对论文问答，组合问题和答案可以识别相同 QA，而不会仅因两个问题相同就合并不同回答。该过程不需要模型推理，适合作为候选池的基础去重步骤。

**输入与输出**

一个或多个文本字段 → 增加去重标签，并输出保留记录。

**使用场景**

适合处理重复运行、片段重叠或模型重复生成造成的相同样本。若希望忽略空白等差异，可在去重前明确执行规范化。

**关键限制**

- 按精确文本识别重复，不自动处理改写或语义等价。
- 单字段应使用 `input_key`；当前只有一个元素的 `input_keys` 不能直接视为等价调用。

[源码](../repos/dataflow/dataflow/operators/general_text/filter/hash_deduplicate_filter.py)

## 三、生成与改写备选

### 10. Text2QAGenerator

**作用与机制**

这个算子用于从材料中构造简短事实问答。它先让模型分析输入材料，生成适合提取 QA 的提示词列表，再将这些提示词与原文组合，执行第二阶段问答生成。

官方自动提示词模板强调清晰、聚焦、可直接验证的事实问题，答案偏向几个词，以便用于 RL 场景的奖励计算。放在 SFT 数据建设中，它可以承担事实问答分支，为术语、数量、数据集名称和明确结论提供较短的样本。

**输入与输出**

原文 → 生成提示词及问题、答案字段；一段原文可以展开为多个提问方向。

**使用场景**

例如，从实验段落提取“使用了哪个数据集”“比较了多少种方法”等 QA。可以与机制解释类样本形成不同的数据类型。

**关键限制**

- 官方任务偏向短答案，不适合作为完整机制解释型 SFT 的唯一生成来源。
- 存在自动提示词解析和 QA 解析两个阶段，接入时需要分别检查各阶段是否产生有效记录。

[源码](../repos/dataflow/dataflow/operators/core_text/generate/text2qa_generator.py)

### 11. SFTGeneratorSeed

**作用与机制**

这个算子将文档内容直接转换为指令—回答样本。它把每行原文填入生成模板，调用模型后，从回复中提取包含 `instruction` 和 `output` 的 JSON 对象，再将成功解析的结果组成输出表。

它适合构造常规问答或解释型样本，也适合与多跳生成器比较不同生成方式。与先组织句间关系的流程相比，它直接把材料交给模型，由生成提示词约束问题和回答的形式。构造时需提供 `custom_prompt`，用于指定附加要求。

**输入与输出**

文档列（默认 `raw_content`）→ 成功解析的 `instruction/output`，并显式带回 `raw_content`；失败解析的结果不进入输出表。

**使用场景**

用于从同一批论文片段生成普通 SFT 候选。当前官方提示词不变的对照中，应固定并记录 `custom_prompt` 配置。

**关键限制**

- JSON 提取使用简单花括号正则，公式花括号或嵌套结构可能造成解析失败。
- 输出表由解析结果重建，除了显式带回的原文，其他来源字段不能假定自动保留。

[源码](../repos/dataflow/dataflow/operators/text_sft/generate/sft_generator_from_seed.py)

### 12. CondorRefiner

**作用与机制**

这个算子用于改进已有问答中的回答，采用“先评价、再改写”的两阶段流程。第一轮将问题和原答案交给模型，生成针对回答的批评意见；第二轮结合问题、原答案和批评意见生成修改后的回答。

它适合尝试处理结构松散、解释不充分或表达重复等问题。例如，原答案已经列出三个步骤，但没有交代步骤间的关系，改写阶段可以重新组织说明。流水线中通常将它放在生成之后、最终评价之前，整个处理包含两轮模型调用。

**输入与输出**

问题＋原答案 → 改写答案；保持记录数量，并写回指定答案列。

**使用场景**

适合已有可用 QA、希望进一步改善表达的情况。做改写对照时，先复制原答案列，后续比较原版与改写版。

**关键限制**

- 当前不独立读取论文原文；论文问答的事实支持需要在改写后另行核对。
- 当前覆盖答案列，需要保留原答案时必须预先复制。

[源码](../repos/dataflow/dataflow/operators/text_sft/refine/condor_refiner.py)

### 13. CondorGenerator

**作用与机制**

这个算子面向按主题组织的通用指令合成。它从配置中的主题、领域和细分方向取样，构造问题生成请求，并解析不同难度的问题；随后根据生成的问题组织回答请求，形成带难度信息的指令数据。

它适合在已经规划好主题范围时扩展问题类型和难度层次。与 CondorRefiner 的输入不同，它从主题配置启动生成，而后者接收现成的问答并改写答案。这里将它列为通用指令分支，便于区分两者的用途。

**输入与输出**

主题、领域及生成配置 → `instruction`、`output`、`difficulty` 等字段。

**使用场景**

适合生成某一领域的入门、中等和困难问题，或补充通用任务数据。

**关键限制**

- 当前生成路径没有读取论文证据，不能直接替换基于指定论文原文的 QA 生成步骤。

[源码](../repos/dataflow/dataflow/operators/text_sft/generate/condor_generator.py)

## 四、评价备选

### 14. DeitaQualitySampleEvaluator

**作用与机制**

这个评价器使用专门训练的 `hkust-nlp/deita-quality-scorer` 对问题—回答对进行质量评分。它把两者放入固定评价模板，读取模型对评分 token 的预测，再将 1～6 分对应的概率进行加权求和，得到连续数值。

它的用途是为候选池增加一种专用模型的质量排序信号。分数写入表格后，可以观察低分样本、比较不同生成分支的分数分布，或交给后续筛选器选择记录。运行时需加载该评分模型和 tokenizer。

**输入与输出**

`instruction`＋`output` → 新增 `DeitaQualityScore`，保留所有待评价记录。

**使用场景**

适合比较专用评分模型与通用模型评价的选择结果，或在已部署专用模型的环境中批量评分。

**关键限制**

- 输入没有独立原文列，不能用于验证答案与论文来源是否一致。
- 需要相应模型权重和运行资源；当前算子使用固定的专用评分模型。

[源码](../repos/dataflow/dataflow/operators/text_sft/eval/deita_quality_sample_evaluator.py)

### 15. DeitaComplexitySampleEvaluator

**作用与机制**

这个评价器用于描述问题本身的复杂程度。它将 instruction 填入复杂度评价模板，使用 `hkust-nlp/deita-complexity-scorer` 预测评分 token，再计算 1～6 分的概率加权结果。

它适合分析数据集的难度组成。例如，查看生成结果是否几乎都是简单名称提问，或为不同复杂度区间分别取样。复杂度分可以与质量分分别保存，从而同时观察“问题有多复杂”和“回答质量如何”。

**输入与输出**

接口读取 `instruction/output` 列，实际评分使用问题文本；新增 `DeitaComplexityScore`。

**使用场景**

适合难度分层、分层抽样或构建具有不同难度比例的训练数据，而不是只追求最高复杂度。

**关键限制**

- 该分数不评价答案质量；接口要求有回答列，也不代表回答参与了复杂度推理。
- 需要加载专用复杂度评分模型，运行配置应与部署环境匹配。

[源码](../repos/dataflow/dataflow/operators/text_sft/eval/deita_complexity_sample_evaluator.py)

### 16. RMSampleEvaluator

**作用与机制**

这个评价器使用奖励模型为问题—回答对提供偏好分数。当前加载 `OpenAssistant/reward-model-deberta-v3-large-v2`，将问题和回答成对编码，经过序列分类模型前向计算，取输出 logits 作为评分。

它适合比较同一问题的多个回答，或给候选池增加一种偏好排序信号。与生成文字批评的评价方式不同，它直接产生数值，结果可以用于排序、分布分析或后续区间筛选。

**输入与输出**

`instruction`＋`output` → 新增 `RMScore`。

**使用场景**

适合已有奖励模型运行环境、需要批量比较回答偏好的场景；在论文流程中可作为辅助评价分支。

**关键限制**

- 当前返回未经 sigmoid 的 logits，不能把分数解释成 0～1 概率；阈值应依据实际分布设定。
- 没有独立原文输入，且成对文本编码会截断超长输入，需注意长论文问答的有效输入范围。

[源码](../repos/dataflow/dataflow/operators/text_sft/eval/rm_sample_evaluator.py)

### 17. SuperfilteringSampleEvaluator

**作用与机制**

这个评价器从语言模型预测答案的难度出发，计算指令跟随难度信号。它分别测量只给答案时的困惑度，以及把指令和可选输入放在答案前面时的条件困惑度，再计算 `IFD = 条件答案困惑度 / 独立答案困惑度`。

困惑度可以理解为模型预测文本的困难程度。这个比值帮助观察指令和输入对答案预测的影响，为数据选择提供一个不同于质量评分的角度。当前实现使用 GPT-2 计算这些数值，再把结果写回样本表。

**输入与输出**

`instruction`＋可选 `input`＋`output` → 新增 `SuperfilteringScore`。

**使用场景**

适合在候选池中研究指令跟随难度，或比较不同难度区间的数据。应结合问题与答案内容解释分数，而不直接按质量分使用。

**关键限制**

- 当前固定使用 GPT-2，并受最大长度设置影响；中文学术文本使用前需要确认指标适用性。
- 空答案或无效数值可能产生空评分，进入数值筛选前需要明确处理方式。

[源码](../repos/dataflow/dataflow/operators/text_sft/eval/superfiltering_sample_evaluator.py)

## 五、评分与筛选合并的备选

以下 Filter 重新计算对应分数并按区间保留记录。它们可以简化已定型流程，但研究阶段采用 Evaluator 保存完整评分，再用 GeneralFilter 比较阈值，更容易分析拒绝样本。

### 18. AlpagasusFilter

**作用与机制**

这个算子把 Alpagasus 整体评价和区间筛选封装为一个步骤。它读取指令、输入材料和回答，调用内部评价器计算分数，将分数写入数据表，再保留满足 `min_score ≤ score ≤ max_score` 的行。

在已经确定评分维度和阈值的流水线中，可以用它代替 AlpagasusSampleEvaluator 与单独的区间规则。论文场景仍可把原文映射到 input，使内部评分请求包含来源材料。

**输入与输出**

指令＋输入材料＋回答 → 带 `AlpagasusScore` 的保留记录。

**使用场景**

适合已确定 Alpagasus 筛选条件、希望简化流水线配置的场景。

**关键限制**

- 它会重新计算分数，不是读取已有评分列直接过滤；复用已有分数时用 GeneralFilter。
- 内部仍是整体评价，输出不包含完整候选池，也不保存模型文字理由。

[源码](../repos/dataflow/dataflow/operators/text_sft/filter/alpagasus_filter.py)

### 19. DeitaQualityFilter

**作用与机制**

这个算子使用 Deita 专用质量模型对问题与回答评分，并立即按配置区间筛选。内部先调用 DeitaQualitySampleEvaluator，再把评分写入结果列，最后输出区间内的记录。

它适合质量评分方法和保留范围已经稳定的批处理流程。通过设置上下界，可以保留某个质量区间，也可以设置宽松上界、主要执行最低质量分要求。

**输入与输出**

`instruction`＋`output` → 带 `DeitaQualityScore` 的保留记录。

**使用场景**

适合直接构建按 Deita 质量分选择的训练子集。若需要多次比较阈值，先单独运行评价器更方便。

**关键限制**

- 会加载模型并重新评分；要复用已保存分数，应改用 GeneralFilter。
- 不读取独立论文证据；质量模型的分数不能作为来源核验结果。

[源码](../repos/dataflow/dataflow/operators/text_sft/filter/deita_quality_filter.py)

### 20. DeitaComplexityFilter

**作用与机制**

这个算子按 Deita 复杂度选择问题。它调用复杂度评价器计算每条 instruction 的分数，再使用上下界保留指定难度区间的记录，同时保留原来的回答供训练使用。

与最低质量筛选相比，这里的区间主要用于组织数据构成。例如，分别导出低、中、高复杂度子集，再按照任务需要组合不同难度比例。

**输入与输出**

`instruction/output` → 带 `DeitaComplexityScore` 的保留记录；实际复杂度判断使用问题。

**使用场景**

适合难度分层或按难度抽取子集，尤其是在已经完成回答质量检查之后。

**关键限制**

- 筛选依据是问题复杂度，不检查答案是否正确；回答质量需要其他评价结果。
- 会重新运行复杂度模型，不能直接当作已有分数列的通用过滤器。

[源码](../repos/dataflow/dataflow/operators/text_sft/filter/deita_complexity_filter.py)

### 21. RMFilter

**作用与机制**

这个算子把奖励模型评价和分数区间选择合并起来。它先读取问题与回答，计算 RM 分数并写入表格，然后保留分数处于上下界之间的记录。

它适合构建符合某种奖励模型偏好的候选子集。区间参数既可以表达最低分要求，也可以有意选择某个分段，用于比较不同偏好分段的数据。

**输入与输出**

`instruction`＋`output` → 带 `RMScore` 的保留记录。

**使用场景**

适合已经观察过奖励分数分布，并确定选择区间的批量数据流程。

**关键限制**

- 分数来自原始 logits，不能按概率含义设置阈值；上界还会排除高于该值的记录。
- 它重新运行奖励模型，且没有独立论文原文输入。

[源码](../repos/dataflow/dataflow/operators/text_sft/filter/rm_filter.py)

### 22. SuperfilteringFilter

**作用与机制**

这个算子把 Superfiltering 的困惑度比值计算与区间筛选组合在一起。它向内部评价器传入问题、可选上下文和答案，取得 IFD 分数，再输出落在配置区间内的记录。

它适合把已确定的指令难度选择策略落实到数据集构建中。可以用不同区间形成子集，比较这些数据的内容特点或后续训练表现。这里的区间表示对难度信号的选择。

**输入与输出**

`instruction`＋`input`＋`output` → 带 `SuperfilteringScore` 的保留记录。

**使用场景**

适合已经明确 IFD 工作区间的流程；探索区间时可先用评价器保存完整分数。

**关键限制**

- 继承 GPT-2 与输入长度的限制，空评分应在正式批量过滤前明确处理。
- 会重新计算困惑度；已有评分表的多阈值比较应使用 GeneralFilter。

[源码](../repos/dataflow/dataflow/operators/text_sft/filter/superfiltering_filter.py)

## 六、去重备选

### 23. MinHashDeduplicateFilter

**作用与机制**

这个算子面向文字大部分相同、但不完全一致的重复记录。它将选定文本拆成片段并构造 MinHash 签名，再通过 LSH（局部敏感哈希）索引查找相似记录，保留未发现近似重复的样本。

当前默认使用字符 n-gram，即连续 n 个字符形成的片段。`ngram` 决定比较粒度，`num_perm` 控制签名规模，`threshold` 控制近似检索的相似度设置。相比精确哈希，它能够处理少量增删或改写造成的近似重复。

**输入与输出**

指定文本字段 → 新增去重标签，并输出保留记录。

**使用场景**

适合清理由文档版本、重叠片段或模板化生成造成的大量文本重合，例如两条 QA 仅多了一句相同背景说明。

**关键限制**

- 它基于文本片段重合进行近似检索，不判断语义等价；少量数字或否定词差异可能被忽略。
- 保留结果受遍历顺序影响，不按质量分自动选择代表样本。

[源码](../repos/dataflow/dataflow/operators/general_text/filter/minhash_deduplicate_filter.py)

### 24. SemDeduplicateFilter

**作用与机制**

这个算子通过文本向量识别语义接近的记录。它先组合选定字段、计算向量并归一化，再构建样本间的余弦相似度矩阵，根据阈值找出相似样本对并过滤记录。

当前使用 `1 - eps` 作为相似度阈值，因此 `eps` 越小，要求的相似度越高。它适合识别词面差异较大但表达内容接近的 QA，可用于精确去重之后进一步压缩重复表达。

**输入与输出**

指定文本字段 → 新增去重标签，并输出保留记录。

**使用场景**

例如，“重排序模块起什么作用”和“候选检索后为什么需要再次排序”可能形成相似候选对，供检查是否需要同时保留。

**关键限制**

- 语义相似不代表条件、数字和结论相同，阈值需要通过实际样本对检查。
- 当前构造完整两两相似度矩阵，内存需求随样本数平方增长；大规模输入不能只按向量编码成本估算。
- 当前按样本顺序标记相似对中的后者，不会自动选出质量最佳的代表样本。

[源码](../repos/dataflow/dataflow/operators/general_text/filter/sem_deduplicate_filter.py)

## 七、如何理解这些选择

| 想回答的问题 | 对应算子 |
|---|---|
| 能否可靠取得论文材料？ | 文档转换、KBCChunkGenerator、KBCTextCleaner |
| 事实短答、普通解释、多跳问答分别适合什么内容？ | Text2QAGenerator、SFTGeneratorSeed、Text2MultiHopQAGenerator |
| 改写能否改善表达并保持事实？ | CondorRefiner |
| QA 是否清晰、切题、有价值？ | Text2QASampleEvaluator |
| 问题、原文与答案的整体表现如何？ | AlpagasusSampleEvaluator |
| 专用模型能否辅助质量排序？ | DeitaQualitySampleEvaluator、RMSampleEvaluator |
| 数据难度组成是否合适？ | DeitaComplexitySampleEvaluator、SuperfilteringSampleEvaluator |
| 哪些规则能保留有效样本？ | GeneralFilter 或专用 Filter |
| 是否存在精确、近似或语义重复？ | Hash、MinHash、Sem 去重算子 |

选择算子时先确定要解决的问题，再检查输入字段、输出结构和执行环境。开发阶段可先保存完整候选与评分，再比较生成方式、改写效果和筛选区间；参数确定后，再用对应的专用 Filter 简化流程。
