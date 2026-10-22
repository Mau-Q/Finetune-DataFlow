# 学校离线平台与训练部署

2026-10-22（Asia/Shanghai）更新。平台已部署到 node01，校内 HTTPS 入口和认证读写检查通过；MinerU advanced 已复用原有模型完成一页解析。Qwen3.5-9B 的训练环境已安装，完整权重仍在传输，短训和 8192 容量结果另行记录。当前实际配置见 [训练方案及执行状态](training/qwen35-9b-node01-l40-8192.md) 与 [audit.json](../deploy/plans/qwen35-9b-8192/audit.json)。

## 校内访问

访问地址：**https://192.168.247.162:18443/**。已从 Mac 直接连接该地址并验证 TLS；其他设备须处于能访问 node01 的校内网络或相应 VPN 中。

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

# 查看训练日志；训练尚未开始时相应文件可能不存在。
tail -n 100 "$HOME/DataFlow/runs/qwen35-9b/20261022-smoke/logs/train-512.log"
```

首次重建容器时参考 [平台启动脚本](../deploy/school/run-platform.sh)、[HTTPS 启动脚本](../deploy/school/run-platform-proxy.sh) 和 [Caddyfile](../deploy/school/Caddyfile)。这些脚本使用已安装环境的本地镜像，不在服务器拉取镜像或联网装包；已有同名容器时不会覆盖。

## 离线安装和备份

Linux x86_64/CPython3.12 物料在 Mac 下载后上传；训练与平台使用独立依赖锁文件。上传后核对服务器文件，再清理本轮 Mac 临时副本，保留版本、哈希、脚本和日志。Caddy 的 Linux 资产也遵循相同流程。

平台已完成 3 个 SQLite 的一致性备份，记录位于 `environments/platform/backup-receipt.json`，备份位于 `environments/platform/backups/`。活跃库不放 NFS；备份包含账号/配置状态，应保存在私有目录。恢复前停止本次平台服务，在独立位置验证备份和业务文件后再切换，不覆盖 Mac 原平台数据。

## 仍需完成的接续

- 正式训练数据继续由 Mac 现有 DataFlow 生成、发布/导出后上传；本轮没有配置校内生成模型服务。
- Mac 本地库当前有 3 个各 1 条的验收发布版本；它们不能作为正式训练集的默认选择。正式数据版本和规模仍待确定，不阻塞构造数据试训。
- 平台 SSH 训练执行器尚未覆盖容器内外一致的文件路径和进程身份；服务器平台也没有复用 Mac Keychain 的 SSH 认证。直接 DataFlex 试训先独立完成，不能把按钮保存或环境探测当成平台训练链路通过。
- MinerU advanced 的独立解析已通过；平台到解析器的远程调用还未集成。
- 单次 HTTPS 读写检查已通过，其他真实成员的浏览器证书信任、账号邀请及跨设备使用尚未代替用户执行。

更多成员权限、人工评测和导出操作见 [局域网团队使用说明](lan-usage.md)。HTTPS 配置沿用 [Caddy 官方反向代理机制](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy) 和内网 CA 机制。
