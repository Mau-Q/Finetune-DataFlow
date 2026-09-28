# 论文数据准备 Pipeline

第一轮真实论文 SFT 开发准备当前采用[结构优先递归切分](CHUNKING-POLICY.md)，切分器对照已取消，SFT 生成 A/B 保留。6 篇论文的 12 个目标页已有解析，源文检查后选取 11 条共同输入、准备 22 个请求，尚未调用生成 API。活动入口为 `data/round1/active-preparation.json`；下面的固定 token 窗口流程是原演示流程。生成对照定义与旧准备记录见 [ROUND1-EXPERIMENT.md](ROUND1-EXPERIMENT.md)。

已保存到本机 WebUI：**论文 PDF → 证据分块（演示，无 LLM）**。

这是后端创建、执行并同步到画布的 Pipeline。前端可以查看和修改算子参数；不需要手动拖拽才能建流程。配置见 `paper-prepare.json`，注册 ID 与字段校验结果见 `paper-prepare.registration.json`。

```text
PDF 清单（source_path）
  → MinerU4PDFParser       parsed_document：快照、文档哈希、解析 ZIP、日志
  → MinerU4PageExtractor   source_page：物理页码、原文、表格、块坐标
  → PaperEvidenceChunker  raw_chunk + chunk_metadata：原文片段及出处
```

分块默认 512 tokens、重叠目标 64 tokens，不跨物理页。字符位置是解析得到的逐页文本的 Unicode 字符区间，不是 PDF 字节位置。块坐标沿用 MinerU 的归一化坐标。每块保留文档 SHA-256、页码、页内区间、相关块和 tokenizer 文件指纹；可以定位 PDF 快照及原始解析产物。空页保留并设置 `eligible_for_qa=false`。正文不经过 LLM 改写。

现有 KBC 解析算子使用旧 MinerU 接口，无法直接调用本机 MinerU 4。这里通过独立 CLI 进程适配；逐页分块额外保留原文区间，便于后续校验 QA 的证据来源。上游算子没有修改。

## 已验证

2026-09-22，后端任务 `8273f63acb84`：演示 PDF 1 份 → 1 页 → 1 个块，54 tokens，三个算子全部完成，约 10 秒。

- 输入：`../data/paper-demo/documents.jsonl`，明确标注 `is_demo=true`，引用安装阶段生成的测试 PDF。
- 结果：`../outputs/paper-demo/8273f63acb84/`，分别保存 `documents.jsonl`、`pages.jsonl`、`chunks.jsonl`。
- 结果也已注册到 WebUI 数据集列表，名称为“论文准备 · 演示证据块（已运行）”。
- 执行记录：`../logs/paper-prepare.execution.json`；文件哈希及验证摘要：`../logs/paper-prepare.verification.json`。
- 5 项契约测试通过：中文/组合字符/表格的分块覆盖与 token 上限、页码及空页保留、解析产物变更检测、缺失字段/覆盖拦截、非法重叠参数。
- Pipeline 校验无错误、无警告；浏览器实测显示数据集节点、3 个算子及连线，并绑定正确的已保存 Pipeline 名称。

以上验证仅覆盖合成测试文档。真实论文的扫描页、多栏、公式和复杂表格仍需抽样核验。保留位置来源不代表 OCR 内容一定正确。

## 操作

在工作区根目录运行：

```sh
# 校验并幂等注册/更新这条演示流程
.venvs/dataflow/bin/python scripts/register-paper-pipeline.py

# 同步到已打开的 WebUI 画布（先打开右上角助手，建立 WebSocket）
.venvs/dataflow/bin/python scripts/register-paper-pipeline.py --render

# 完全不依赖 GUI，直接执行同一套算子
.venvs/dataflow/bin/python -m paper_dataflow.pipelines.paper_prepare \
  --workspace "$PWD" \
  --input "$PWD/data/paper-demo/documents.jsonl" \
  --output "$PWD/outputs/paper-prepare-cli"

# 本地契约检查，不调用生成模型
.venvs/dataflow/bin/python -m unittest discover \
  -s extensions/paper-dataflow/test -p 'test_paper_preparation.py' -v
```

刷新网页后，可从顶部“Pipeline”选择已保存的流程；后端配置不会因页面刷新丢失。右上角不应再显示“临时 Pipeline”。WebUI 同步逻辑已修正，避免后端推送后保存/运行仍指向旧流程。

接入真实 PDF 时，另建 JSONL，每行包含一份本地 PDF 的绝对路径 `source_path`，并标注实际来源；不要把真实文档混入演示清单。后端登记数据集后，把 Pipeline 的输入换成新数据集。每次执行保留独立 PDF 快照与解析目录，不复用可能过期的解析缓存。

## 已接入原 SFT2000 基线

完整目标为：**证据分块 → QA 生成 → 证据一致性审核 → 过滤/去重 → SFT 导出**。

生成/审核服务已在 UI 配置，详见 [SERVING_STATUS.md](SERVING_STATUS.md)。原 2000 条基线的生成、独立审核、过滤/去重与 SFT 导出已另存为三算子流水线，详见 [SFT2000.md](SFT2000.md)。2000 条归档响应离线回放一致，默认真实调用输入限三条冻结证据。1199 篇 TXT 已登记为来源目录；TXT 不具有原 PDF 页码坐标。密钥不写入 Pipeline JSON。

正式对照前仍需固定完整候选输入和独立评价集。当前历史 2000 条均为被接受的 train 记录，仅用于迁移回归。分块 tokenizer 仅用于 PDF 准备阶段，SFT2000 最终长度检查已经使用旧基线冻结的 Qwen3.6 tokenizer 与聊天模板。
