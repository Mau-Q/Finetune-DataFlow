# 学校服务器部署建议（初版与当前状态）

2026-10-22 更新：已连通 school1/mgt01 与 node01。**下文原生安装步骤属于连通前的初版参考，不作为当前执行方案。** 当前建议将平台集中部署在 node01 的独立容器中，mgt01 作为现有跳板；训练、平台、MinerU 分开环境。详见 [Qwen3.5-9B 单 L40、8192-token 环境准备方案](training/qwen35-9b-node01-l40-8192.md)。本轮仅整理文档，没有安装、部署或训练。

## 当前 SSH 状态

历史上 school 使用密码认证。后续已按用户授权创建专用加密密钥、登记用户本人公钥，并配置 macOS Keychain。当前正式别名为 school1，school 为兼容别名；可无交互登录 mgt01。node01 通过 school1 跳转，使用已保存可信主机指纹。长期连接约定在本机 `~/.codex/AGENTS.md` 与 `~/.codex/server-connections.md`，不把私钥或密码写入仓库。

node01 实测为 CentOS 7/glibc 2.17、4 张 L40/驱动 550.127.08、Docker 26.1.4/overlay2；Docker 位于本地 /home 分区，剩约 138 GB。mgt01 的根分区剩约 2.1 GB，Docker 位于 NFS 且使用 vfs；因此当前优先评估 node01。当前 GPU 均有占用；现有模型服务的可访问性不等于训练资源授权或空闲。

## 推荐形态

当前采用容器隔离宿主旧系统的依赖；前端预构建。平台数据库/活跃状态放 node01 本地持久卷，PDF/固定产物/只读权重可按权限使用 NFS。生成和审核先保留已授权的兼容 API；学校现有 Qwen 服务的复用需确认负责人与使用额度，不能仅凭模型名称替换。模型推理可用不等于微调环境可用。

MinerU 已有 `mineru-easyread:4.0.12-pro2605-bf16` 镜像和用户自有模型目录，可优先复用；当前平台 basic/standard CLI 适配与学校 advanced/vLLM 路线仍需适配，不能声称直接接通。训练模型固定为 Qwen3.5-9B，使用独立环境，以完整样本 8192 tokens 为目标。

先通过 SSH 隧道单人验收，再按学校网络条件启用校园网 HTTPS。多人入口使用现有 `scripts/start-lan.sh` 启动的认证网关；网关只绑定 127.0.0.1，HTTPS 代理是共享入口。不要用开发自动登录的 `scripts/webui.sh` 作为多人服务，也不要把私有项目 worker 端口或 `app.main` 直接暴露。

使用一个网关进程与服务器本地磁盘存储 SQLite/任务产物。不要未经验证增加 uvicorn workers，也不要把活跃 SQLite 放到共享 NFS 上。开发者能配置执行 Python，适合互相信任的组内开发者；项目隔离不等于针对恶意开发者的系统沙箱。普通审核者使用受限角色。

## 初版原生部署步骤（历史参考，当前不执行）

### 1. 代码与平台环境

在有写权限的专用目录检出确定的根仓库提交和其固定 submodule 提交。准备 Git、uv、Node.js 22、npm 和 C/C++ 编译器。不要复制 macOS 的 `.venvs`。

仓库 `scripts/setup.sh` 默认编译器为 macOS 路径。Linux 上应按机器的实际编译器覆盖，例如：

```sh
CC=cc CXX=c++ ./scripts/setup.sh
```

这会初始化缺失子模块、创建 Python 3.12 环境、安装 Core/论文扩展/后端并构建前端。该命令依赖服务器联网和可安装的轮子；当前没有 Linux 实测结论。现有 locks 中的机器快照不应视为跨平台全量安装清单。

### 2. PDF 解析环境

在独立 `.venvs/mineru` 中安装和当前适配器 CLI 协议匹配的 MinerU，准备模型和本地 tokenizer，并分别验证 CLI 入口及小 PDF 解析。

当前 `scripts/mineru.sh` 使用本地 `models/mineru`、torch 小模型后端、llama-cpp VLM 引擎与 `mineru-kit` 入口。不能把 macOS 包快照直接搬到 Linux；也不能只因服务器有 CUDA 就任意替换后端而不验证解析产物协议。平台环境与解析环境分开，避免解析依赖冲突影响 WebUI。

### 3. 认证与单人验收

在服务器交互式初始化管理员，密码由使用者在终端输入，不写在命令或仓库中：

```sh
./scripts/start-lan.sh init --name ADMIN
```

首次只通过 SSH 隧道测试 HTTP 时，认证 cookie 的 Secure 属性需与 HTTP 对应；可仅在这次 loopback 测试进程中关闭，不能沿用为校园网明文共享服务：

```sh
DATAFLOW_DEV_AUTO_LOGIN=0 DATAFLOW_COOKIE_SECURE=0 ./scripts/start-lan.sh
```

本机另开终端转发：

```sh
ssh -N -L 18001:127.0.0.1:8001 school
```

浏览器打开 `http://127.0.0.1:18001`，确认必须正常登录，检查静态页面、会话和保存后回读。此阶段不调用模型，不触发任务。

### 4. 校园网共享与常驻

使用学校已有 HTTPS 代理/证书，或由管理员部署 Caddy，反代至 127.0.0.1:8001。仓库 `deploy/Caddyfile.lan` 是内网模板；`tls internal` 需要客户端信任对应 CA，不等于自动获得公开可信证书。域名、网卡地址和防火墙开放范围需由实际校园网条件决定。

HTTPS 正式进程使用 `DATAFLOW_COOKIE_SECURE=1`、`DATAFLOW_DEV_AUTO_LOGIN=0`。通过用户 systemd 服务或学校提供的进程管理方式运行 `scripts/start-lan.sh`，固定 WorkingDirectory、绝对启动路径、数据目录与日志位置。若没有用户 systemd/linger，先使用学校允许的进程托管方案。不能把关闭 SSH 后进程仍存在当作可靠自启动验收。

代理转发要保留请求 Host 和正确的转发协议信息；登录和写请求依赖同源检查。应遵循现有网关与代理配置，不临时放宽 Origin 或绕过认证。

### 5. 数据、模型和 Pipeline 迁移

优先为服务器新建项目和受管资源，避免整库复制本机开发会话与用户状态：

1. 上传有权使用的 PDF 到服务器项目，注册服务器可访问的来源路径。
2. 在服务器配置生成与审核服务，由授权使用者录入密钥；核查网络出口与费用。
3. 导入两个提示词和两个 JSON Schema，记录服务器新 ID。
4. 新建 Pipeline，重绑数据集、服务、提示词、Schema ID；重写 MinerU、tokenizer 和输出目录绝对路径。
5. 只保存并检查配置；先用确定性测试验证解析/字段/审核解析，再经授权用一份论文运行模型。

本机 `pipelines/paper-multitask-low-cost` 已保存提示词、Schema 和配置快照，但注册助手使用开发登录，不能直接当成正式服务器导入程序。

### 6. 验收与备份

分开记录平台启动、认证隔离、PDF 解析、模型 API、审核质量、数据收集和训练各阶段证据。首轮人工抽查生成样本，核对论文页码、表格数字和局部/全文范围；配置通过不代表这些已经通过。

在升级前备份项目配置、受管数据、任务/解析产物、提示词、Schema、模型服务配置与协作数据库。备份可能含密钥，应限制访问；活跃 SQLite 使用其备份能力或停服一致性备份。恢复应先在隔离目录演练，再切换服务，不覆盖正在工作的本机项目。

## 参考

- 仓库 `docs/lan-usage.md`、`scripts/start-lan.sh`、`deploy/Caddyfile.lan`。
- Caddy 官方反向代理说明：https://caddyserver.com/docs/caddyfile/directives/reverse_proxy

资源配置应在 SSH 只读盘点后确定。现阶段无需先承诺 Docker、GPU 推理或公网域名，也没有对这些做远端变更。
