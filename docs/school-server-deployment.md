# 学校离线平台与训练部署

2026-10-22（Asia/Shanghai）更新。平台已部署到 node01，校内 HTTPS 入口和认证读写检查通过；MinerU advanced 已复用原有模型完成一页解析。Qwen3.5-9B 的训练环境已安装，完整权重已上传校验，构造数据短训、adapter 重载与显存上限测试已完成：优化分配器后 7168 token 通过，8192 token 在当前共享显存预算下 OOM；独占整卡估计约 1 万 token。当前实际配置见 [训练方案及执行状态](training/qwen35-9b-node01-l40-8192.md) 与 [audit.json](../deploy/plans/qwen35-9b-8192/audit.json)。

## 校内访问

访问地址：**https://192.168.247.162:18443/**。已从 Mac 直接连接该地址，并通过 TLS、登录、匿名 API 拦截、保存后重新登录回读和退出检查；其他设备须处于能访问 node01 的校内网络或相应 VPN 中。

首次使用先导入并信任 [DataFlow 内网 CA 公共证书](../deploy/school/node01-dataflow-root-ca.crt)，再访问上面的地址。该证书对应 Caddy 的内网 CA，不是公开 CA 自动签发的证书；没有自动修改任何客户端的系统信任设置。公共证书 SHA-256 指纹：

```text
95:DE:19:30:E8:46:50:D3:6F:AB:0A:CC:9E:D6:57:D3:6C:CF:65:7B:D4:B9:4D:0B:83:D1:8C:15:57:D8:68:89
```

管理员账号为 `huruiqian`。随机初始凭据只保存在服务器平台容器的 `/state/admin-bootstrap.json`（0600）；未写入日志、镜像或仓库。管理员在自己的 SSH 终端查看后登录，并在平台修改密码。其他成员通过“协作与人工评测 → 团队设置”接受各自的邀请码、设置密码并获得项目角色；没有创建共享通用账号。

当前使用认证网关 `app.team_gateway`，开发自动登录关闭，Cookie 的 Secure 属性已开启。同源 Origin、CSRF、账号及项目权限校验保留。算子/Pipeline 列表、HTTPS 登录、设置保存后重新登录回读均已通过；未把这些检查写成完整数据生成或平台训练执行成功。

## 入口和运行资源

| 用途 | 当前部署 |
| --- | --- |
| 校内 HTTPS | `rui-dataflow-https-20261022`，Caddy 2.11.7，只监听私网地址的 18443 端口 |
| 平台 | `rui-dataflow-platform-20261022`，宿主仅映射 `127.0.0.1:18001`；不直接开放项目 worker |
| 活跃平台状态/SQLite | 本地 Docker 卷 `rui-dataflow-platform-state-20261022` |
| 旧的固定 backend/data 资源路径 | 本地卷 `rui-dataflow-platform-legacy-data-20261022` |
| 训练 | 独立容器 `rui-qwen35-9b-smoke-20261022`，指定单张 L40；直接 DataFlex 路线 |
| MinerU | 原有 `mineru-easyread:4.0.12-pro2605-bf16` 镜像和用户原有模型；新容器完成 advanced 一页解析 |

服务器统一根目录为 `/sharedata/home/huruiqian/DataFlow`。应用代码只读挂载，模型、固定产物和离线物料保存在 NFS；活跃 SQLite 和编译缓存使用 node01 本地 Docker 存储。没有更改已有推理/MinerU 容器、驱动或宿主 Conda。

平台和 HTTPS 代理配置为 `unless-stopped` 重启策略；已核对配置，未执行服务器重启来测试。Caddy 内网 CA 私钥只留在服务器私有的 `environments/platform-proxy/state`，不复制给客户端。

## 启停与日志

以下命令在核实 node01/huruiqian 身份后执行。连接遵循本机 `~/.codex/server-connections.md`；school1 是 mgt01 跳板，node01 使用既有可信主机指纹和加密密钥，不复制私钥。

```sh
# 查看平台/代理日志。
docker logs --tail 100 rui-dataflow-platform-20261022
docker logs --tail 100 rui-dataflow-https-20261022

# 重启本次新建的服务，数据卷保留。
docker restart rui-dataflow-platform-20261022
docker restart rui-dataflow-https-20261022

# 查看已完成的训练日志。
tail -n 100 "$HOME/DataFlow/runs/qwen35-9b/20261022-smoke/logs/train-512.log"
```

首次重建容器时参考 [平台启动脚本](../deploy/school/run-platform.sh)、[HTTPS 启动脚本](../deploy/school/run-platform-proxy.sh) 和 [Caddyfile](../deploy/school/Caddyfile)。这些脚本使用已安装环境的本地镜像，不在服务器拉取镜像或联网装包；已有同名容器时不会覆盖。

## 离线安装和备份

Linux x86_64/CPython3.12 物料在 Mac 下载后上传；训练与平台使用独立依赖锁文件。上传后核对服务器文件，再清理本轮 Mac 临时副本，保留版本、哈希、脚本和日志。Caddy 的 Linux 资产也遵循相同流程。

平台已完成 3 个 SQLite 的一致性备份，记录位于 `environments/platform/backup-receipt.json`，备份位于 `environments/platform/backups/`。活跃库不放 NFS；备份包含账号/配置状态，应保存在私有目录。恢复前停止本次平台服务，在独立位置验证备份和业务文件后再切换，不覆盖 Mac 原平台数据。

## PDF 到 SFT 的运行方式

学校端已接入论文模板 `论文 PDF → 科研多任务 SFT · 个人 API`。成员在材料库上传 PDF，在模板中选择材料和自己的生成、审核 Serving，检查后提交。个人 Serving 的执行位置选“我的电脑”；Mac / Windows 执行器使用同一平台账号登录，复用现有 Serving 地址、模型和 Key。具体启动命令见 [个人 API 执行说明](personal-api-execution.md)。

链路依次完成：文件哈希与来源登记 → MinerU advanced → 逐页结构提取 → 本地 tokenizer 切块和上下文预算 → 个人电脑生成 → 严格 JSON 检查 → 个人电脑独立审核 → 审核结果匹配 → 长度检查和精确去重 → 受管 SFT 草稿。只有 PASS 且长度合格的样本进入训练数据；REJECT、REVIEW、重复、超长及原始模型响应保留在审计产物中。正式使用前仍需人工抽检并发布版本。

当前学校默认上下文预算 3000 token，块预算 2800，每个上下文最多生成 2 条，完整训练序列上限 6144。预算使用现有 Qwen3.5-9B tokenizer，不在服务器下载。配置在 `/work/paper-workflow.json`；修改配置仅影响后续安装的模板，已有 Pipeline 保留提交时参数。

解析桥只接收带认证的 PDF 内容，平台容器没有 Docker socket 权限。宿主按需创建本项目独立的离线 MinerU 容器，复用原镜像和模型；同一时刻解析一个 PDF。同一批连续请求复用已加载的 advanced VLM 模型，空闲 5 分钟后容器自行退出并释放显存；运行中的解析定期续租，即使宿主桥退出也不会永久占用 GPU。每篇的布局/OCR 子流程仍单独执行。只有新建模型时检查至少 16 GB 空闲显存，不停止其他人的任务。尚未验证数千篇吞吐。

解析桥目前采用独立进程，没有配置宿主自动开机启动。服务器重启后，在核实 node01/huruiqian 身份后执行：

```sh
python3 "$HOME/DataFlow/app/deploy/school/start-mineru-bridge.py"
```

该命令检测已启动的服务，不重复创建进程。日志在 `environments/platform/mineru-bridge/server.log`，每个解析作业的输入、日志、ZIP 和哈希回执在该目录的 `jobs/`；模型启动日志在 `engines/`。回执记录是否复用了模型及总耗时。错误先检查对应作业日志，不直接重跑商业请求。

## 代码与运行数据位置

| 内容 | 学校位置 | 用途 |
| --- | --- | --- |
| 应用代码 | `/sharedata/home/huruiqian/DataFlow/app` | Mac 代码同步后只读挂入容器 `/app` |
| 活跃数据库、项目数据 | Docker 卷 `rui-dataflow-platform-state-20261022`，容器 `/state` | 账号、项目、Serving、任务、材料库、生成与发布数据；不随代码同步覆盖 |
| 环境配置、解析作业、tokenizer、备份 | `/sharedata/home/huruiqian/DataFlow/environments/platform`，容器 `/work` | NFS 大文件与恢复副本；活跃 SQLite 在本地卷 |
| Mac 开发默认运行目录 | `repos/dataflow-webui/backend/data` 与 `cache_local` | 既有本地数据；后续可用 `DATAFLOW_WORKSPACE_DIR` 指向独立目录，迁移须先备份并验证 |

Serving 文件包含凭据，数据库、任务响应和备份也可能含个人数据，不作为普通代码提交。同步代码时保留学校与 Mac 各自的运行数据。解析缓存、任务快照和发布版本有相互引用，当前没有自动清理策略；不要按临时文件随意删除。

## 训练衔接与验证边界

发布版本可导出 Alpaca JSONL；在既有训练容器中用 [输入验证脚本](../deploy/school/validate-sft-input.py) 按 `qwen3_5_nothink` 检查真实 token 数、监督答案和 6144 上限。该脚本不加载模型权重、不训练。生成链路完成不会自动启动训练。

平台 SSH 训练执行器尚未覆盖容器内外一致的文件路径和进程身份；服务器平台也没有复用 Mac Keychain 的 SSH 认证。直接 DataFlex 试训独立完成，不能把按钮保存或输入校验当成平台训练执行成功。任务及算子时间已改为携带时区，避免服务器与浏览器时区不同造成运行时长偏差；既有记录不作猜测性迁移。真实 Windows 电脑、其他成员证书与邀请流程，以及大规模多篇吞吐仍需实机验收。

更多成员权限、人工评测和导出操作见 [局域网团队使用说明](lan-usage.md)。HTTPS 配置沿用 [Caddy 官方反向代理机制](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy) 和内网 CA 机制。
