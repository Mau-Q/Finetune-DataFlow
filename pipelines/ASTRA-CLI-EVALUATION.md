# Codex CLI 独立质量评估

用户指定 GPT Astra high，通过 Codex CLI 执行；仅评价 SFT 质量，不统计或比较 Astra 用量和费用。生成及生产验证成本仍属于方法对比指标。

本机检查：`codex-cli 0.155.1`，`codex login status` 返回 ChatGPT 已登录。适配器已通过离线测试。用户随后已明确授权“进行并启动实验”，覆盖此前暂停；本轮生产完成后自动通过 CLI 评估最终导出。真实调用状态以运行目录的事件和结果为准。

## 输入和结果

入口为 `scripts/astra-quality-eval.py`，依赖现有 `.venvs/dataflow` 中的 jsonschema。上游生产流程完成并固定最终导出后，转换为 JSONL，每行仅含：

```json
{"arm":"A","candidate_id":"原共同输入的 candidate_id","question":"最终问题","answer":"最终答案","source_evidence":"共同输入的完整 evidence"}
```

只纳入最终导出，排除生产拒绝及错误候选。脚本检查 candidate_id、证据逐字一致、每组每条输入至多一个输出，以及总数不超过 22。是否真实属于最终导出由 `scripts/run-round1.py` 的生产清单负责证明，脚本不把字段完整误当生产验收。

`prepare` 固定源导出、证据、脚本、rubric、schema 的 SHA-256，创建随机匿名 ID，并随机排列顺序。匿名输入只包含 ID、问题、答案、证据；组别映射另存 `private-map.json`，不发送给模型。

每条调用独立 `codex exec`，显式指定模型及 high，忽略用户 config，禁用 shell、浏览器、应用、插件、子代理等工具入口及项目 AGENTS 注入，使用空临时工作目录和只读沙箱。提示词要求不调用工具；响应事件一旦出现工具活动则判为运行失败。以上是盲评的上下文隔离措施，并非对所有宿主级策略的安全隔离证明。

使用 CLI 的 `--output-schema` 和 `--output-last-message` 接收 JSON，保存实际命令、提示词、CLI 原始事件、错误、响应和质量结果。不提取或汇总 Astra 用量；CLI 原始日志保留其本身的事件字段。模型字段标为 requested model，不将 CLI 配置值冒充已独立验证的服务端模型版本。

七维度和合格定义见 [astra-quality-rubric.md](astra-quality-rubric.md)。JSON 结构、匿名编号、引用原文和正常完成事件均须验证。单条失败或超时即停止，保留记录；不自动重试、不覆盖已有 execution 目录。空导出不调用模型，质量标为无法估计。固定产物不会按评估结果回写修改。

## 操作

在工作区 `/Users/rui/Documents/DataFlow` 中，正式产物生成后先进行纯本地准备：

```sh
.venvs/dataflow/bin/python scripts/astra-quality-eval.py prepare \
  --input /absolute/path/to/final-exports.jsonl \
  --output /absolute/path/to/new-evaluation-bundle

.venvs/dataflow/bin/python scripts/astra-quality-eval.py run \
  --bundle /absolute/path/to/new-evaluation-bundle
```

第二条默认 dry-run，不调用模型。之后明确启动评估时，在 `run` 命令末尾添加 `--execute`。不需要新建 API Key，也不修改全局 Codex 配置。串行，每条最多 600 秒，wrapper 不重试，并关闭 CLI 的无界重试功能。CLI 内置 provider 不允许覆盖配置，内部有限重试沿用 CLI 行为，不承诺每次 CLI 启动只有一次 HTTP 请求；真实运行之前不宣称传输行为已验证。

离线测试：

```sh
.venvs/dataflow/bin/python -m unittest discover -s scripts -p test_astra_quality_eval.py -v
```

参数依据：[Codex 非交互模式](https://learn.chatgpt.com/docs/non-interactive-mode)、[配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)，并核对了本机 CLI help 和 feature 列表。
