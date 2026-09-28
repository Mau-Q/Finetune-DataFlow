# 原 SFT2000 基线服务接入

2026-09-22 已核对用户在 WebUI 保存的服务。密钥仅由本地服务管理使用，本文件不记录密钥。

| 参数 | 生成 | 审核 |
| --- | --- | --- |
| WebUI 名称 | 生成 | 测试 |
| Serving ID | a9885c5b9907017b | 99e05909b12873c2 |
| 模型 | qwen3.7-plus | deepseek-v4-pro |
| api_url | https://maas.qianwenaiapi.com/compatible-mode/v1/chat/completions | https://api.deepseek.com/chat/completions |
| temperature | 0.2 | 0.0 |
| 思考参数 | enable_thinking=false | thinking={"type":"disabled"} |
| max_tokens | 2048 | 3200 |
| response_format | {"type":"json_object"} | {"type":"json_object"} |
| max_workers | 1 | 1 |
| UI max_retries（当前实现为总尝试次数） | 1 | 2 |
| connect_timeout / read_timeout | 10 / 60 秒 | 10 / 120 秒 |

Qwen 地址由用户填写的 `/compatible-mode/v1` 补齐为完整 Chat Completions 地址。沿用用户选择的新千问平台入口；它与历史记录中的 DashScope 域名不同。当前单并发用于联调，不等同于历史整体最大并发 48；请求超时和重试异常分类也不能视为历史实现的精确复现。

## 修正和验证

- WebUI 的 `configs` 原本被作为嵌套同名字段传入，现统一展开为 DataFlow Serving 的额外关键字参数。服务测试、普通执行、Ray 执行及 embedding 初始化都接入同一个转换函数。
- 拦截非对象配置与覆盖专用服务字段的配置；兼容旧 JSON 字符串形式。
- JSON 模式的服务测试明确要求返回 JSON，避免默认“你好”测试提示与 JSON 模式要求不一致。
- 移除普通和 Ray Serving 初始化时输出明文密钥的日志；普通初始化错误上下文不再包含完整服务配置。
- 4 项离线测试通过，包含两种模型经过服务测试入口和普通执行引擎后发送的模拟 HTTP 请求。核对模型、温度、思考开关、JSON 格式和 token 上限；Ray 路径做了语法检查，未启动 Ray 作业。
- 重启后，两条真实服务测试均返回 `{"ok":true}`：Qwen 约 1.25 秒，DeepSeek 约 1.38 秒。仅发送合成连通性提示，没有论文数据。

证据：`../logs/serving-params-tests.log`、`../logs/serving-connectivity.json`。

## 当前边界

旧基线 Pipeline 已另行接入并注册到 UI，见 [SFT2000.md](SFT2000.md)。这条流水线通过 UI Serving 取得端点与密钥，复用旧 gateway 的超时和传输重试逻辑；普通 DataFlow Serving 的实现不因此改变。默认三条证据用于真实联调。没有启动 2000 条重新生成或 SFT 训练；正式受控对照还需要固定完整候选输入与独立评价集。
