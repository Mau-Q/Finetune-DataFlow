# 2026-10-24 收尾证据

用户授权：先回归、将已有工作及文档删除合并推送至 main，再清理学校旧权重、重复 checkpoint 和 Mac 旧备份，停止空闲训练容器；保留最新八组结果、模型、环境和证据。

- `regression-and-first-push.json`：本地回归结果及首次推送本地/远端同一版本的记录。
- `school-result.json`：学校删除量、保留文件验证计数、八组最终权重哈希，以及完整预删除计划和删除日志的哈希。
- `school-deleted.jsonl`：131 个已删除文件的相对路径、大小、SHA-256 和原因；路径基准见报告中的学校运行根目录。
- `mac-result.json`、`mac-deleted.jsonl`：Mac 备份清理结果与逐文件删除记录。
- `containers-after.json`：三个训练容器已停止，平台及 HTTPS 继续运行；容器 ID、镜像和挂载保持一致。
- `audit-manifest.json`：本目录文件及本地完整计划的哈希索引。
- `source-archive/`：本次实际使用的一次性清理脚本，供审计使用，不是通用清理命令。学校脚本的 plan 模式由执行器注入原始证据清单，apply 使用服务器已冻结的计划；固定数量断言与已有回执检查会拒绝直接重复执行。

完整保留文件清单在学校运行目录和 Mac 的 `outputs/closeout-20261024/` 中保留，本目录只提交紧凑结果与删除记录。原始运行证据和历史哈希清单未改写；本目录解释主动清理导致的历史权重缺失。

详细说明见 [收尾记录](../../../../docs/training/dataflex-closeout-20261024.md)。
