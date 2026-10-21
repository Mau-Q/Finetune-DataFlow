# 安装与启动

## 源码和环境

主要本地验证环境为 macOS Apple Silicon。需要 Git、uv、Node.js 22 和 npm；安装依赖与首次模型调用需要网络。uv 负责在工作区创建 Python 3.12 环境。

```sh
git clone --recurse-submodules https://github.com/Mau-Q/Finetune-DataFlow.git
cd Finetune-DataFlow
./scripts/setup.sh
```

不使用 MM 研究源码时，可不递归克隆，安装脚本只初始化 Core 与 WebUI 两个必需子模块。脚本不会重置已有子模块或替换现有虚拟环境；组件版本不同会停止并提示，先检查本地改动再决定更新。安装会修改目标虚拟环境中的依赖和重建前端，已有可用环境无需重复运行。

`locks/components.json` 固定源码提交。`locks/dataflow.txt`、`mineru.txt` 等是旧机器的环境快照，部分包含 editable 绝对路径、平台相关包，不能直接 `pip install -r` 作为通用重建方法。当前安装依据组件的项目元数据、WebUI 依赖和测试叠加依赖；尚未承诺跨平台完整依赖锁定。

## 运行

```sh
./scripts/webui.sh --daemon
./scripts/webui.sh --status
./scripts/webui.sh --stop
```

打开 `http://127.0.0.1:8000/`，MCP 为 `http://127.0.0.1:8000/mcp`。前台调试运行 `./scripts/webui.sh`。日志在 `repos/dataflow-webui/.backend.log`。此项目没有登录与多用户隔离，默认作为本机工具使用。

更新前端后，进入 `repos/dataflow-webui/frontend` 执行 `npm run build` 并刷新页面；后台模式更新 Python 后，在没有任务写入时停止并重新启动。

## Windows PowerShell

Windows 原生环境使用根目录 `.venv` 时，不要执行默认的 `scripts/setup.sh` 和 `scripts/webui.sh`：它们面向 Unix 环境并固定使用 `.venvs/dataflow/bin/python`。请在 PowerShell 中执行：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\setup-windows.ps1
.\scripts\webui-windows.ps1 -Action Foreground
```

启动后会在当前 PowerShell 中打印：

- `.venv` 激活状态和实际 Python 路径
- 后端启动日志
- `http://127.0.0.1:8000` 的服务地址

保持这个窗口打开即可使用 WebUI；停止时按 `Ctrl+C`。

如果已经完成安装，只需再次运行：

```powershell
.\scripts\webui-windows.ps1 -Action Foreground
```

后台模式仍然可用，但日志会写入文件：

```powershell
.\scripts\webui-windows.ps1 -Action Daemon
.\scripts\webui-windows.ps1 -Action Status
```

停止后台服务：

```powershell
.\scripts\webui-windows.ps1 -Action Stop
```

安装脚本会检查每个外部命令的退出码；子模块检查、依赖安装或前端构建失败时会立即停止。后台服务未就绪时也会返回失败；`Stop` 会核验进程路径和启动参数，发现旧 PID 被其他程序占用时会拒绝停止并提示检查 PID 文件。

可用以下命令运行隔离的 Windows 回归测试（包含超过 10 秒的锁等待，不会调用模型服务）：

```powershell
.\scripts\test-windows.ps1 -Python .\.venv\Scripts\python.exe
Push-Location repos\dataflow-webui\backend
try { & ..\..\..\.venv\Scripts\python.exe -m unittest discover -s platform_tests -v }
finally { Pop-Location }
```

GitHub Actions 同时运行 Windows 持久化测试、Windows PowerShell 5.1 和 PowerShell 7 脚本测试。

Windows 安装路径不安装可选的 Langkit 评估依赖，因此不需要编译 `whylogs-sketching` 或安装 Visual Studio C++ 工具；LangkitFilter 和 LangkitSampleEvaluator 在该环境中不可用，其余 WebUI 流程保持不变。

这些 Windows 兼容性修复涉及 `repos/dataflow` 和 `repos/dataflow-webui` 子模块。向 GitHub 提交时，需要先分别在对应子模块提交并推送，再在根仓库提交更新后的子模块指针。

## 第一次生成

1. 按 [API 配置](model-api.md) 新建模型服务。
2. 导入 `repos/dataflow-webui/examples/representative-training/text-one.jsonl`。
3. 选择代表性文本 SFT 模板，为模型节点绑定服务，保存为自己的流程。
4. Save & Run，选择新建或追加数据集、结果目录。
5. 对照原文核对最终样本、模型原始响应及无效样本记录。

图片测试可导入示例目录的 `images/` 六张合成图片。`manual-reference.json` 是人工核对资料，不作为输入。

## 常见问题

- 缺少 `paper_dataflow`：确认使用工作区 `.venvs/dataflow/bin/python`，并安装 `extensions/paper-dataflow`。不要将 Core 和 MM 的同名 `dataflow` 包装入同一环境。
- API 返回 401/404：核对密钥、模型名和完整 `/chat/completions` URL。配置保存并不证明远端可用。
- 图片请求失败：模型须支持多模态 `image_url` 及 base64 data URL，并允许当前图片大小。
- `fasttext-wheel` 编译失败：macOS 需要可用的 Command Line Tools；脚本默认使用 `/usr/bin/clang` 和 `/usr/bin/clang++`。
- 端口被占用：先确认已有实例及任务状态；启动脚本不会替你终止其他进程。

## 可选论文 PDF 路线

四类 API 示例流程不要求安装 MinerU。历史 13 步论文流程使用独立 `.venvs/mineru`、本地解析模型和 tokenizer，必须额外准备；`scripts/setup.sh` 不安装这些资源。

```sh
./scripts/mineru.sh parse /absolute/path/paper.pdf -o outputs/paper.zip --format zip --tier standard
```

旧 DataFlow MinerU API 与独立 MinerU4 路线存在接口差异，见 [历史安装调研](archive/INSTALLATION_RESEARCH.md) 与 [论文流程说明](../pipelines/README.md)。不要将历史本机配置直接视为新机器可运行配置。
