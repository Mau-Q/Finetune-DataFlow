# 安装与启动

## 源码和环境

本地开发已在 macOS Apple Silicon 与 Windows 11 实测。需要 Git、uv、Node.js 22 和 npm；安装依赖与首次模型调用需要网络。uv 负责在工作区创建 Python 3.12 环境。每位开发者分别安装并运行自己的后端；Windows 的步骤见下方 PowerShell 章节。

```sh
git clone https://github.com/Mau-Q/Finetune-DataFlow.git
cd Finetune-DataFlow
./scripts/setup.sh
```

不需要递归克隆，安装脚本只初始化 Core 与 WebUI 两个必需子模块。脚本不会重置已有子模块或替换现有虚拟环境；组件版本不同会停止并提示，先检查本地改动再决定更新。安装会修改目标虚拟环境中的依赖和重建前端，已有可用环境无需重复运行。

`locks/components.json` 固定源码提交。`locks/dataflow.txt`、`mineru.txt` 等是旧机器的环境快照，部分包含 editable 绝对路径、平台相关包，不能直接 `pip install -r` 作为通用重建方法。当前安装依据组件的项目元数据、WebUI 依赖和测试叠加依赖；尚未承诺跨平台完整依赖锁定。

## 运行

```sh
./scripts/webui.sh --daemon
./scripts/webui.sh --status
./scripts/webui.sh --stop
```

打开 `http://127.0.0.1:8001/`。本地开发默认自动进入“默认工作区”，首次启动自动创建独立的“本地开发者”身份，不需要管理员密码。每位开发者在自己的电脑运行实例，数据库、账号、任务和模型服务配置都保存在本机，不通过 Git 同步。

前台调试可运行 `./scripts/dev.sh` 或 `./scripts/webui.sh`；日志在终端，后台日志在 `repos/dataflow-webui/.backend.log`。前后端热更新开发可另开终端，在 `frontend` 目录运行 `npm run dev`，Vite 会把 `/team` 和 `/api` 转发到 `8001`。修改后端代码需在没有任务运行时重启后端；网关会管理私有项目进程。

退出后当前标签页停留在登录页；点击“进入本地工作区”可重新进入。已有管理员账号保留，开发身份不复用管理员密码。测试正常登录流程可运行 `./scripts/dev.sh --require-login`，或用 `DATAFLOW_DEV_AUTO_LOGIN=0 ./scripts/webui.sh`。新机器如需使用普通账号，先按 [团队指南](lan-usage.md) 初始化管理员，再选择正常登录模式。

开发模式仅允许本机连接和本机 Host，不支持把端口转发给其他人；局域网部署使用独立的 `start-lan.sh`，默认不开启开发自动登录。产品内 Agent/MCP 入口已移除。

更新前端后，进入 `repos/dataflow-webui/frontend` 执行 `npm run build` 并刷新页面；后台模式更新 Python 后，在没有任务写入时停止并重新启动。

## Windows PowerShell

Windows 原生环境使用根目录 `.venv` 时，不要执行默认的 `scripts/setup.sh` 和 `scripts/webui.sh`：它们面向 Unix 环境并固定使用 `.venvs/dataflow/bin/python`。请在 PowerShell 中执行：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\setup-windows.ps1
.\scripts\webui-windows.ps1 -Action Foreground
```

首次运行会自动创建本机开发身份并进入默认工作区；不需要其他电脑上的管理员账号。启动后会在当前 PowerShell 中打印：

- `.venv` 激活状态和实际 Python 路径
- 后端启动日志
- `http://127.0.0.1:8001` 的服务地址

保持这个窗口打开即可使用 WebUI；停止时按 `Ctrl+C`。

如果已经完成安装，只需再次运行：

```powershell
.\scripts\webui-windows.ps1 -Action Foreground
```

需要测试正常登录时运行 `.\scripts\webui-windows.ps1 -Action Foreground -RequireLogin`。

后台模式仍然可用，但日志会写入文件：

```powershell
.\scripts\webui-windows.ps1 -Action Daemon
.\scripts\webui-windows.ps1 -Action Status
```

停止后台服务：

```powershell
.\scripts\webui-windows.ps1 -Action Stop
```

安装脚本会检查每个外部命令的退出码；子模块检查、依赖安装或前端构建失败时会立即停止。后台服务未就绪时也会返回失败；`Stop` 会核验进程路径和启动参数，发现旧 PID 被其他程序占用时会拒绝停止并提示检查 PID 文件。Windows 后台停止会终止该实例的整个进程树，请先确认没有生成任务运行。

可用以下命令运行隔离的 Windows 回归测试（包含超过 10 秒的锁等待，不会调用模型服务）：

```powershell
.\scripts\test-windows.ps1 -Python .\.venv\Scripts\python.exe
Push-Location repos\dataflow-webui\backend
try { & ..\..\..\.venv\Scripts\python.exe -m unittest discover -s platform_tests -v }
finally { Pop-Location }
```

GitHub Actions 同时运行 Windows 持久化测试、真实私有进程启停和凭证隔离测试、Windows PowerShell 5.1 和 PowerShell 7 脚本测试。这些检查不等于完整 Windows 安装、浏览器和模型调用验收；完整验收步骤见 [Windows 开发验收](windows-development.md)。

Windows 安装路径不安装可选的 Langkit 评估依赖，因此不需要编译 `whylogs-sketching` 或安装 Visual Studio C++ 工具；LangkitFilter 和 LangkitSampleEvaluator 在该环境中不可用，其余 WebUI 流程保持不变。

已有检出更新前先停止服务并检查主仓库的 `git status --short --branch`，保存自己的修改，再执行：

```powershell
git pull --ff-only
.\scripts\setup-windows.ps1
.\scripts\webui-windows.ps1 -Action Foreground
```

源码随主仓库更新。完整离线回归使用 `.\scripts\test-local.ps1`；实际通过范围和跳过原因见 [Windows 实机验收](windows-acceptance.md)。

Core、WebUI、DataFlex 源码直接在总仓库中提交；只有可选 MM 使用子模块。

## 第一次生成

1. 按 [API 配置](model-api.md) 新建模型服务。
2. 导入 `repos/dataflow-webui/examples/representative-training/text-one.jsonl`。
3. 选择代表性文本 SFT 模板，为模型节点绑定服务，保存为自己的流程。
4. Save & Run，选择新建或追加数据集、结果目录。
5. 对照原文核对最终样本、模型原始响应及无效样本记录。

图片测试可导入示例目录的 `images/` 六张合成图片。`manual-reference.json` 是人工核对资料，不作为输入。

## 常见问题

- 缺少 `paper_dataflow`：Unix 确认使用 `.venvs/dataflow/bin/python`，Windows 确认使用 `.venv\Scripts\python.exe`，并运行对应安装脚本安装 `extensions/paper-dataflow`。不要将 Core 和 MM 的同名 `dataflow` 包装入同一环境。
- API 返回 401/404：核对密钥、模型名和完整 `/chat/completions` URL。配置保存并不证明远端可用。
- 图片请求失败：模型须支持多模态 `image_url` 及 base64 data URL，并允许当前图片大小。
- `fasttext-wheel` 编译失败：macOS 需要可用的 Command Line Tools；脚本默认使用 `/usr/bin/clang` 和 `/usr/bin/clang++`。
- 端口被占用：先确认已有实例及任务状态；启动脚本不会替你终止其他进程。
- 中文路径或测试结果乱码：通过 Windows 启动、回归脚本运行，它们给 Python 及子进程设置 `PYTHONUTF8=1`。手动执行 Python 时先设置 `$env:PYTHONUTF8='1'`；不要把 UTF-8 数据改存为 GBK。
- 首次进入画布较慢：完整项目进程冷加载 CPU 依赖需要时间，当前就绪上限为 180 秒。超过时限检查 `backend/data/collaboration/default.worker.log`，不要删除数据库重试。
- 终端无法直连网络而浏览器可以：Git、uv、npm 不一定自动继承 Windows 系统代理。仅在当前终端为对应工具配置自己的有效代理，保留证书校验；不要提交个人代理地址或凭据。

## 可选论文 PDF 路线

四类 API 示例流程不要求安装 MinerU。历史 13 步论文流程使用独立 `.venvs/mineru`、本地解析模型和 tokenizer，必须额外准备；`scripts/setup.sh` 不安装这些资源。

```sh
./scripts/mineru.sh parse /absolute/path/paper.pdf -o outputs/paper.zip --format zip --tier standard
```

旧 DataFlow MinerU API 与独立 MinerU4 路线存在接口差异，见 [历史安装调研](archive/INSTALLATION_RESEARCH.md) 与 [论文流程说明](../pipelines/README.md)。不要将历史本机配置直接视为新机器可运行配置。
