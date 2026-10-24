# DataFlex 流程验证收尾与清理记录

日期：2026-10-24（Asia/Shanghai）。本轮目标是验证八种策略的训练、保存、重载、评测及证据汇总流程能够完成；不据此判断策略优劣。本次收尾没有启动新的 GPU 训练，也没有部署下一轮实验方案。

## Git 与回归

按用户指定顺序，先完成回归，再提交文档删除，将工作分支快进合并到 `main`，并正常推送。首次推送后，本地和远端主分支均为 `5800ad5c150f7cccdb905f1256a9ee5e3cdd6504`；相对原远端主分支包括 19 个已有提交及 1 个文档删除提交。没有强制推送。

| 检查 | 结果 |
| --- | --- |
| `./scripts/test-local.sh`：Core CPU | 165 通过，1 deselected |
| 同一脚本：WebUI 后端 | 491 通过，另有 7 个 subtests 通过 |
| 同一脚本：论文扩展 | 54 通过 |
| DataFlex 回归及策略实验契约 | 48 通过、6 跳过，另有 8 个 subtests 通过 |

6 个跳过项依赖 Mac 本地环境中未安装的实际 LLaMA-Factory 或 PEFT。此次本地回归不替代此前学校 GPU 实验和学校环境中的验证。旧的 stash 和已合并工作分支仍保留；`pipelines/SFT-PIPELINE-OPERATORS.md` 的删除已正式提交。

## 学校产物清理

连接 `school1` 核对 `mgt01/huruiqian`，再以既有可信 `node01` 主机指纹核对训练节点 `node01/huruiqian`。删除范围严格限制在：

`/sharedata/home/huruiqian/DataFlow/runs/qwen35-9b/20261022-smoke`

清理前复核原证据清单中的 926 份文件、最新八组最终 adapter，以及末步 checkpoint 与最终 adapter 的一致性。冻结删除清单并复制到 Mac 后才执行删除。

| 已删除内容 | 数量 |
| --- | ---: |
| 历史轮次、门测及诊断运行的 adapter 权重 | 99 |
| 最新八组中被最终输出替代的 checkpoint-12 权重 | 8 |
| 与最终 adapter 相同的 checkpoint-24 权重 | 8 |
| 与各组最终输出相同的 checkpoint tokenizer | 16 |

共删除 131 个文件，20,236,508,368 字节，约 18.85 GiB。清理后逐项核对保留的 3,637 份运行文件和 69 份环境证据文件，内容哈希保持一致。checkpoint 目录中的小型状态记录、参数、说明文件仍然保留；其中已删除权重的目录不能再直接用于恢复训练。

最新八组最终结果保留在：

`/sharedata/home/huruiqian/DataFlow/runs/qwen35-9b/20261022-smoke/strategy-20261023/gpu1-core8-20261024`

每组可用最终 adapter 仍位于 `G00` 至 `G07` 各自的 `attempt1/output/`，权重合计 1,385,508,096 字节。基座模型、共享初始 adapter、冻结数据、预测、日志、梯度诊断文件、环境、有效离线依赖均保留。没有清理其他项目、其他用户的任务、Docker 镜像或缓存卷。

原有证据哈希清单仍作为**清理前快照**保留，没有修改以隐藏已删除文件。核查当前状态时，应结合本次删除清单及保留验证回执；不能再要求旧清单中的所有历史权重仍然存在。

## Mac 备份精简

仅清理 `repos/dataflow-webui/backend/backups/datasets/` 中的 21 份旧快照，共 762,334,582 字节，约 727.02 MiB。保留基线与最近三份快照，四份压缩包均通过完整性检查：

- `snapshot-20261019T091404983261Z-baseline.zip`
- `snapshot-20261021T132426270756Z.zip`
- `snapshot-20261021T142428733618Z.zip`
- `snapshot-20261022T081948007385Z.zip`

其余 221 份备份和恢复验证文件逐项核对保持一致。本机模型、虚拟环境、项目数据、论文生成产物及原有证据未清理。

## 容器状态与证据入口

停止前重新确认三个容器只有 `sleep` 进程，随后停止：

- `rui-dataflex-strategy-gpu1-20261024`
- `rui-dataflex-strategy-gpu2-20261023`
- `rui-qwen35-9b-smoke-20261022`

容器本身、对应镜像及完整挂载配置保留。平台和 HTTPS 容器继续运行。挂载核对按完整记录进行无序比较，避免将 Docker 返回顺序变化误判成挂载变化。

两端清理的文件逻辑字节数合计约 19.56 GiB；这是删除文件大小总和，不作为共享文件系统独占回收空间的测量。

紧凑证据见 [收尾证据目录](../../deploy/plans/dataflex-strategy-20261023/closeout-20261024/README.md)。完整学校预删除与保留清单位于上述运行根目录下的 `strategy-20261023/closeout-20261024/school-plan.json`，Mac 副本及完整备份计划位于 `outputs/closeout-20261024/`。逐文件删除记录保留路径、大小和 SHA-256。

本报告和紧凑证据另保存一份学校审计副本：`/sharedata/home/huruiqian/DataFlow/environments/qwen35-9b/closeout-20261024/`。该副本不修改既有部署、训练环境或原始运行证据。

最终流程验证报告仍为 [GPU1 八组流程验证报告](dataflex-gpu1-unified-core8-results-20261024.md)；其中运行时状态是当时快照，当前容器与产物去留以本收尾记录为准。
