# DataFlex 本地与学校代码、配置对照

2026-10-23（Asia/Shanghai）。先只读核对，随后用户授权本地与学校代码、配置均可修改，且 GPU 可以更换。所有训练类回归均使用 CPU 小张量，未加载 Qwen 权重、未执行 GPU 训练。

## 实际环境与修改前状态

- 经 `school1` 确认 `mgt01/huruiqian`，再到 `node01/huruiqian`。
- 训练容器：`rui-qwen35-9b-smoke-20261022`，network=none；检查时只有 sleep，无训练进程。
- DataFlex 位于 `/usr/local/lib/python3.12/dist-packages/dataflex`。修改前 75 个 Python/默认配置文件与本地完全同哈希，平台抽查的 7 个训练相关文件也一致。
- 实际环境：Python 3.12、DataFlex 1.1.0、LLaMA-Factory 0.9.6.dev0、Torch 2.6.0、Transformers 5.5.4、PEFT 0.18.1、Accelerate 1.11.0、bitsandbytes 0.49.2、FLA/fla-core 0.4.2、causal-conv1d 1.6.0。TRAK 未安装，不把 LESS 等列为即刻可运行。
- 历史实际训练均为 static、microbatch1、accumulation1、2步，`components.yaml={}`；候选 YAML 中的 accumulation16 不代表实际执行值。
- 模型真正位于容器 `/models/Qwen3.5-9B`；旧 candidate 额外拼 revision 后的路径不存在，`/inputs/data` 也不存在。新配置不再沿用这些占位路径。
- 平台缺少 `/app/repos/dataflex`，只读调用实际 `snapshot_source` 返回 TrainingError；训练数据库为空，没有固定训练主机、训练计划或运行。
- 原训练容器绑定物理 GPU3 的 UUID；本轮某次快照可用约22GiB，变化中的共享资源不能替代实际开跑前的检查。

## 已修改与部署的内容

1. `Registry.build` 允许组件通过 `**kwargs` 接收配置，同时只把构造函数明确需要的 runtime 对象传入，避免将整份 trainer runtime 泄漏给组件基类。
2. DoReMi 训练 loss 改为可微逐样本 CE，与 domain 权重相乘；默认 smoothing=0 也生效；保留独立样本的 label smoothing、有效标签归一化和梯度。缺失标签/域、标量 fallback、非有限损失均明确报错。自定义 loss 明确由 Trainer 处理 accumulation 缩放，不误用模型的 token 归一化声明。
3. MixTrainer 不再把 domain_id 传给模型 forward；ODM 与 Lego 保留完整微批域标签。当前标量反馈不支持混域微批，改为明确拒绝，避免把整批归因到第一个域。没有宣称已实现逐域反馈或完整 ODM 论文复现。
4. 发布本次仓库构建版本 `1.1.0+dataflow.20261023`，离线构建并正常解析已安装依赖后安装，仅替换 DataFlex；未升级 Torch/Transformers 等依赖，pip check 通过。
5. 补齐学校平台挂载源目录 `/sharedata/home/huruiqian/DataFlow/app/repos/dataflex`，保留 UPSTREAM.json 和实际源码。平台源码快照仍记录原上游 commit，加 dirty/hash 标识本次改动，没有伪造为未改的上游版本。
6. 生成并部署8组独立 YAML。`model_name_or_path=/models/Qwen3.5-9B`、`dataset_dir=/runs/strategy-20261023/data`，每组输出和缓存分开；没有覆盖历史 smoke 配置与产物。

部署目录：

| 用途 | 学校宿主路径 | 训练容器路径 |
| --- | --- | --- |
| 源码、wheel、验证日志 | `/sharedata/home/huruiqian/DataFlow/environments/qwen35-9b/strategy-20261023` | `/work/strategy-20261023` |
| 8组配置与未来数据/输出 | `/sharedata/home/huruiqian/DataFlow/runs/qwen35-9b/20261022-smoke/strategy-20261023` | `/runs/strategy-20261023` |
| 模型 | 既有只读模型挂载 | `/models/Qwen3.5-9B` |

运行目录暂在既有 `/runs` 挂载的独立子目录下，与旧产物不重叠。如果换 GPU 而建立新专用容器，应保持同一容器路径契约，显式记录新的宿主绑定；不用修改旧历史目录来迁就新路径。

容器环境本身未持久设置 `TORCHINDUCTOR_COMPILE_THREADS` 和 `PYTORCH_CUDA_ALLOC_CONF`；旧 smoke.py/run-smoke.sh 曾在启动时设置。新测试实际启动必须显式带 `TORCHINDUCTOR_COMPILE_THREADS=1`、`PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`、两个 HF offline 变量。不能以旧脚本曾设置为由假定新 CLI 会继承。

## 已执行验证与证据边界

- Mac：8项 DataFlex CPU回归通过，5项实际 LLaMA-Factory 相关检查跳过；配置物化2项通过；平台训练管理17项回归通过。
- 学校：从新源码运行13项，再从正常安装后的包运行13项，均通过，无跳过；CUDA_VISIBLE_DEVICES 置空，使用小张量和真实已安装 LLaMA-Factory 的 trainer 方法。
- 修改后回读：学校正常安装包、本地源码和学校平台源码树的75个文件再次逐一同哈希；平台实际源码快照函数通过，产出81个快照文件。
- 8组配置的模型路径和组件文件均存在；参数字段按实际 parser 使用的 LLaMA-Factory `TrainingArguments` 及 DataFlex 扩展参数核对，无未知字段。该检查没有加载模型或完整实例化 GPU TrainingArguments，不代替启动验收。
- 检查覆盖 kwargs 传播、ODM 奖励与归一化、混域拒绝、mask与打分batch一致性、DoReMi默认加权loss/梯度、label smoothing及拒绝静默退化。
- 这些检查不等于 Qwen3.5 GPU 训练、长时稳定性、完整 DoReMi 三阶段流程或策略效果比较。实际梯度累积与训练调度仍需按主方案在真实 trainer 运行中验证。
- 8组训练配置已生成，但真实训练数据未准备，消费/权重观察 runner 尚未实现。不会把配置文件存在标记为训练就绪。

机器可读摘要：[school-reconciliation.json](../../deploy/plans/dataflex-strategy-20261023/school-reconciliation.json)。详细回读和原始日志索引保存在本地 `outputs/dataflex-strategy-school-audit-20261023/`；摘要保留其哈希。

## 接续次序

1. 固定352条真实数据、split和token预算，完成实际消费/权重观察钩子。
2. 开跑前刷新GPU信息；用户允许换卡，按实时空闲选择。现有容器只能访问其绑定UUID，不能仅改容器内CUDA_VISIBLE_DEVICES来切到宿主其他GPU。建立新专用容器或重配空闲专用容器时保留所有其他任务。
3. 分别验证B1/B2显存与短训，再运行8组核心项目。
4. 平台源码快照问题已修；平台固定训练主机、容器执行适配与真实运行记录仍需后续验收，不提前配置一个无法执行的主机记录或伪造训练计划。
