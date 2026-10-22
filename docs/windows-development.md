# Windows 本机开发与验收

本指南针对每个人在自己的电脑独立运行项目。无需连接 Mac、不需要其他开发者的账号，也不把数据库、密钥、虚拟环境、缓存或结果推送到 Git。

## 获取代码与安装

需要 Git for Windows、uv、Node.js 22/npm。推荐 Windows 11 x64、Python 3.12，使用普通 PowerShell 5.1 或 PowerShell 7。路径允许空格和中文；首次验收建议放在较短路径，减少上游包的长路径限制。

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
```

本次 Mac 验证覆盖自动登录、会话退出、完整空工作区初始化、生产构建、隔离持久化和真实私有工作进程。Windows 原生依赖安装、系统选择器显示、完整浏览器交互及真实模型任务仍需在 Windows 实机执行。CI 平台测试使用小型服务验证进程通信，不代表 Ray 或 GPU 模型执行已通过。

## 结构说明

- `scripts/dev_server.py`：跨平台开发启动入口，限定回环监听；`windows_server.py` 保留为兼容包装。
- `app/team_gateway.py`：同源会话、权限及 API 转发。
- `app/services/development_access.py`：本机开发访问条件；`TeamStore.development_login` 管理独立开发身份。
- `app/services/project_workers.py`：项目进程生命周期、就绪检查、随机凭证和不受代理环境影响的本机传输。
- `app/services/worker_auth.py`：工作进程私有入口校验。
- `app/services/desktop_picker.ps1`：Windows 原生选择器适配；Python 端统一解析 UTF-8 JSON。

可移植的是代码和安装步骤，不是包含绝对路径的历史运行数据。跨机器共享流程后需重新绑定输入、输出目录与模型服务。
