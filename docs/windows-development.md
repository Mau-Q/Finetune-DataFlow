# Windows 本机开发与验收

本指南针对每个人在自己的电脑独立运行项目。无需连接 Mac、不需要其他开发者的账号，也不把数据库、密钥、虚拟环境、缓存或结果推送到 Git。

## 获取代码与安装

需要 Git for Windows、uv、Node.js 22/npm。推荐 Windows 11 x64、Python 3.12，使用普通 PowerShell 5.1 或 PowerShell 7。路径允许空格和中文；首次验收建议放在较短路径，减少上游包的长路径限制。

先检查当前终端实际使用的工具：

```powershell
git --version
uv --version
node --version
npm --version
$PSVersionTable.PSVersion
```

缺少 Git 或 uv 时可使用官方包的 winget 入口：

```powershell
winget install --id Git.Git --exact --source winget
winget install --id astral-sh.uv --exact --source winget
```

安装后重新打开 PowerShell，使新 PATH 生效。Node.js 22 从 [官方 v22 下载目录](https://nodejs.org/dist/latest-v22.x/) 选择对应架构安装包；已有其他版本可用独立工具目录并只调整当前终端 PATH，不必覆盖其他项目的 Node。不要假定名称为 LTS 的包仍然是 22。本次分别使用 Node 22/npm 完成测试构建、系统 Node 24/npm 完成安装脚本；推荐开发与 CI 保持 Node 22。

首次克隆不需要可选的 DataFlow-MM 子模块：

```powershell
git clone https://github.com/Mau-Q/Finetune-DataFlow.git
Set-Location Finetune-DataFlow
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\setup-windows.ps1
.\scripts\webui-windows.ps1 -Action Foreground
```

打开 <http://127.0.0.1:8001/>。默认自动创建并复用“本地开发者”和“默认工作区”。现有管理员不会被修改。Python 环境位于 `.venv`，与 Mac 的 `.venvs/dataflow` 分开；不要从 Mac 复制这两个目录。

安装过程从本地 Core 源码和 WebUI 依赖构建，不安装可选 Langkit，不下载大模型。可选 MinerU、MM、远程 Linux/GPU 训练不是本次 Windows 本机 UI 验收的一部分。真实生成需要你在自己的 WebUI 配置模型 API。

已有检出的更新方式：先提交或暂存自己的修改，再执行下面的命令。子模块更新会切到根仓库固定提交，不要在含未保存修改的子模块中直接运行。

```powershell
git pull --ff-only
git submodule update --init -- repos/dataflow repos/dataflow-webui
.\scripts\setup-windows.ps1
```

## 日常开发

后端前台运行：

```powershell
.\scripts\webui-windows.ps1 -Action Foreground
```

前端热更新另开终端：

```powershell
Set-Location repos\dataflow-webui\frontend
npm run dev
```

打开 Vite 打印的本机地址。默认代理到 `http://127.0.0.1:8001`，可用 `DATAFLOW_DEV_BACKEND` 修改代理目标。修改后端 Python 后，在无运行任务时 Ctrl+C 停止并重新启动；只刷新浏览器不会重新加载项目进程。

需要普通登录时增加 `-RequireLogin`。点击“退出”会停留在登录页，不会立即自动进入；“进入本地工作区”按钮可恢复开发身份。自动登录开关只由本机开发启动入口设置，LAN 部署入口默认关闭。开发模式拒绝非回环连接和外部 Host。

后台操作：

```powershell
.\scripts\webui-windows.ps1 -Action Daemon
.\scripts\webui-windows.ps1 -Action Status
# 确认没有任务执行后再停止；会停止此实例及其子进程。
.\scripts\webui-windows.ps1 -Action Stop
```

日志：`repos/dataflow-webui/.backend.log`、`.backend.error.log`，项目进程日志：`backend/data/collaboration/default.worker.log`。PID 不匹配时脚本拒绝停止其他程序。

## 验收顺序

1. 首次访问直接进入画布，侧边栏显示“本地开发者”；刷新后身份和工作区保持。
2. 退出后刷新仍停留登录页，点击“进入本地工作区”可再次进入。
3. 浏览算子库，添加算子、编辑参数、保存并重新打开流程；打开数据集、任务和人工评测页面。
4. 使用 Windows 原生选择器选择文件及文件夹，检查含中文和空格的本地路径；取消选择不报错。
5. 导入 `repos/dataflow-webui/examples/representative-training/text-one.jsonl`，配置你自己的 API，为每个模型节点绑定服务。
6. 选择文本 SFT 模板，指定本机结果目录运行；检查真实步骤进度、日志、结果预览、自动收录和下载。此步骤会调用你的模型 API。
7. 重启后端，确认流程、来源、任务、草稿、样本与发布版本保留。
8. 后台启动、Status、Stop 后，确认本实例项目进程退出、端口可再次使用。

离线回归（不调用模型）：

```powershell
.\scripts\test-windows.ps1 -Python .\.venv\Scripts\python.exe
Push-Location repos\dataflow-webui\backend
try { & ..\..\..\.venv\Scripts\python.exe -m unittest discover -s platform_tests -v }
finally { Pop-Location }
Push-Location repos\dataflow-webui\frontend
try { npm test; if ($LASTEXITCODE -ne 0) { throw 'Frontend tests failed' }; npm run build; if ($LASTEXITCODE -ne 0) { throw 'Build failed' } }
finally { Pop-Location }
.\scripts\test-local.ps1
```

`test-local.ps1` 是 `test-local.sh` 的 Windows 等效入口，依次运行 Core CPU、WebUI 后端和论文扩展测试；统一使用 `.venv`、平台路径分隔符和 `PYTHONUTF8=1`，任一步失败立即停止。直接调用 Python 测试前也应设置 `$env:PYTHONUTF8='1'`，保证子进程和中文夹具一致。5.1 / 7 脚本检查可分别执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test-windows.ps1 -Python .\.venv\Scripts\python.exe
pwsh -NoProfile -File scripts/test-windows.ps1 -Python .\.venv\Scripts\python.exe
```

Windows 实机已验证完整依赖安装、上述页面基础操作、系统选择器、持久化和本地 Ray CPU 无模型流程，逐项证据见 [Windows 实机验收记录](windows-acceptance.md)。平台测试的小型进程夹具、固定模型响应回放和真实无模型执行分别记录，不能互相代替；真实模型 API、SSH、GPU 训练仍为 NOT_RUN。

## 无模型验收流程

无需配置模型服务即可复测本地执行与结果链路：

1. 导入 `repos/dataflow-webui/examples/representative-training/text-one.jsonl`，命名为自己的离线验收来源。
2. 新建自定义 Pipeline 并选中该来源，添加原生 `PandasOperator`。初始化参数 `process_fn` 使用列表，内容为：

   ```json
   ["lambda df: df.assign(instruction='离线验收：回显原文', input='', output=df['text'])"]
   ```

3. 运行参数 `output_key` 设为 `output`。再添加 `RemoveExtraSpacesRefiner`，其 `input_key` 设为 `output`，手动连接前序节点。自动连线开关只同步已有运行边的参数关系，不会替未连接节点建立顺序边。
4. 自动排版、检查配置、保存并重新打开流程。Save & Run，选择新的验收数据集，选择含中文和空格的本机目录后开始。
5. 查看真实任务状态、步骤数、耗时、日志、结果预览和自动收录，下载 JSONL 核对一条记录及 `instruction/input/output`。这是确定性的本地转换，不是模型生成或质量证明。无真实百分比时页面只展示步骤数和不确定状态。
6. 发布 v1 后停止并重启，重新打开来源、流程、任务、草稿、样本和发布版本。保留真实运行数据，不用删除数据库的方式让检查通过。

## 实机排错

- 首次进画布会冷加载较多 CPU 依赖，项目进程就绪上限为 180 秒；失败检查 `backend/data/collaboration/default.worker.log`，不要反复并发启动。
- 若浏览器能访问网络而 Git / uv / npm 不能，检查终端工具是否继承了自己的代理。本次直连 GitHub 失败、使用既有本机代理后成功；不需要重新登录，也没有禁用 TLS 校验。
- uv 的缓存与工作区在不同盘时出现 hardlink 警告会自动复制，不是安装失败；可在当前终端设置 `$env:UV_LINK_MODE='copy'`。
- 原生选择窗口由带置顶父窗口的 Windows Forms 适配打开。取消时返回空数组；页面保留原值，不作为错误。LAN 使用浏览器上传，不开放任意主机路径。
- 后台标准输出和错误日志均在 WebUI 根目录，并被 Git 忽略。临时测试输出不应提交。
- 未提供历史论文 tokenizer / SFT2000 回放数据的首次检出会明确跳过相关测试；无需为本地 UI 下载模型。Linux 训练 runner 的 POSIX 进程组检查在 Windows 跳过；符号链接实测需系统允许创建链接，否则明确跳过。
- 远程训练 `execution_ref` 指的是 Linux 主机上的绝对路径，与 Windows 本地输入文件路径分开；保存或导出方案不会启动 SSH / GPU。

## 结构说明

- `scripts/dev_server.py`：跨平台开发启动入口，限定回环监听；`windows_server.py` 保留为兼容包装。
- `app/team_gateway.py`：同源会话、权限及 API 转发。
- `app/services/development_access.py`：本机开发访问条件；`TeamStore.development_login` 管理独立开发身份。
- `app/services/project_workers.py`：项目进程生命周期、就绪检查、随机凭证和不受代理环境影响的本机传输。
- `app/services/worker_auth.py`：工作进程私有入口校验。
- `app/services/desktop_picker.ps1`：Windows 原生选择器适配；Python 端统一解析 UTF-8 JSON。

可移植的是代码和安装步骤，不是包含绝对路径的历史运行数据。跨机器共享流程后需重新绑定输入、输出目录与模型服务。
