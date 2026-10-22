# Windows 实机验收（2026-10-22）

本记录来自 Windows 11 本机执行及有界面的真实 Chrome 浏览器，不以 HTTP 200 或静态源码检查代替交互验收。每台电脑独立安装、运行和保存账号及数据；不连接其他开发者的后端。下面的无模型流程使用公开示例和确定性转换，不代表模型生成或数据质量验证。

## 环境与源码

| 项目 | 实际版本 |
| --- | --- |
| Windows | Windows 11 家庭版中文版，10.0.26300，x64 |
| Windows PowerShell | 5.1.26100.9711 |
| PowerShell | 7.6.5 |
| Git for Windows | 2.55.0.windows.5 |
| uv | 0.13.4（winget 官方包安装） |
| Python | 根目录 `.venv`，CPython 3.12.10，本机已有解释器创建 |
| 前端测试与构建 | Node.js 22.23.4 / npm 10.9.9，官方 ZIP 校验 SHA-256 后独立解压 |
| 系统原有 Node/npm | 24.20.0 / 12.2.0，安装脚本也在此组合下成功完成 |
| 浏览器 | Playwright CLI 0.1.22，有界面 Chrome 156 |
| 主要 Python 包 | torch 2.14.1、Ray 2.59.0、FastAPI 0.159.1、uvicorn 0.54.0、numpy 1.26.4、transformers 4.57.6 |

首次检查目录为空且非 Git 仓库，无原有文件、提交或改动需要保留。直接检出主仓库 main，仅按 gitlink 初始化两个必需子模块，未初始化 DataFlow-MM。开始及推送前获取远程 main，验收起点没有超出用户指定基线的更新：

| 仓库 | 实际验收起点 |
| --- | --- |
| Finetune-DataFlow | `63e0c28eb35a7fedee8c4d4b2ece458938f69945` |
| DataFlow Core | `b5b69c144617abf24005bb61db5ab7e2cef865e7` |
| DataFlow-WebUI | `7bb03a42a32db7f819ef933820b20aa1d4b83456` |

交付代码在以上基线继续修复，子模块的最终版本以同一主仓库提交中的 gitlink 和 `locks/components.json` 为准，可用以下命令核对，不把起点当成最终交付提交：

```powershell
git log -1 --format='%H %s'
git submodule status -- repos/dataflow repos/dataflow-webui
Get-Content locks/components.json
.\.venv\Scripts\python.exe scripts/check-workspace.py
```

## 安装与命令

实际执行的入口如下，适用于项目根目录；无需激活其他机器的环境：

```powershell
git submodule update --init -- repos/dataflow repos/dataflow-webui
.\scripts\setup-windows.ps1
.\scripts\webui-windows.ps1 -Action Foreground
# 前台服务停止后：
.\scripts\webui-windows.ps1 -Action Daemon
.\scripts\webui-windows.ps1 -Action Status
.\scripts\webui-windows.ps1 -Action Stop
```

默认入口为 `http://127.0.0.1:8001/`。首次直连 GitHub 失败，使用电脑既有的本机代理后克隆、下载成功；GitHub CLI 已登录 Mau-Q，无需再次登录。未关闭证书验证、扩大监听范围或取消访问控制。uv 跨盘缓存的 hardlink 警告自动降级为复制。安装不含可选 Langkit、MinerU/MM、模型权重或 GPU 训练环境。

## 实际发现、修复和复测

| 问题 | 修复与结果 |
| --- | --- |
| 初次安装后项目进程加载 CPU 依赖超过 60 秒，Pipeline 请求 503 | 有限就绪等待改为 180 秒，本机后续重启、私有工作进程和页面访问正常；不靠删除数据重试 |
| 本机开发会话因 `team.enabled` 被当成 LAN，原生导入按钮退化为浏览器文件上传 | 传递明确的 development 状态，仅本机开发恢复原生选择器；新增前端测试同时保留 LAN 上传限制 |
| Windows 原生对话框缺少父窗口，可能藏在浏览器后 | 集中在已有 `desktop_picker.ps1` 创建置顶父窗口；真实窗口选择中文空格文件、文件夹并返回路径，取消正常 |
| Windows 同一时钟刻度保存导致 `updated_at` 重复，旧编辑覆盖保护失效 | 在共享资源存储增加持锁调用的单调修订时间；Prompt/Schema 共用，固定时钟和并发冲突回归通过 |
| Linux 训练执行引用被 Windows `Path.is_absolute` 误判 | 对远端引用使用 `PurePosixPath` 并拒绝反斜杠；本地输入仍按本机路径读取，打包测试通过 |
| 前端源码截取测试假定 LF，在 Windows CRLF 下 5 项失败 | 测试读取时规范化行结束符，88 项前端测试通过，未改写整库换行 |
| 用户取消未保存编辑后，标签页标题已提前跳到目标页 | 路由成功后再更新标题；Vite 浏览器确认取消保留内容与原题名 |
| Core 注册表检查误报已明确省略的可选 Langkit | 测试静态核验两个可选声明，仅在包未安装时排除对应动态注册断言；未改 Core 注册表语义 |
| Unix 完整回归入口不能原生用于 Windows | 新增 `test-local.ps1`，统一 `.venv`、UTF-8、路径分隔符和逐步退出码检查；5.1 参数默认值解析问题亦经实测修复 |
| 首次完整测试依赖个人历史资源或 POSIX 环境 | 缺失 tokenizer / 历史回放数据、Linux runner 和无权限真实符号链接分别明确跳过，不伪造通过 |
| Windows 后台错误日志未被子模块忽略 | 增加 `.backend.error.log` 忽略规则；运行文件不提交 |

没有新建 Windows 业务分支或第二套 UI。平台窗口适配保留在小型 PowerShell 模块；启动、资源修订与路径处理复用现有服务。没有改动 Core 注册表的既有加载语义。

## 浏览器与真实无模型执行

| 检查 | 实际结果 |
| --- | --- |
| 首次自动登录、刷新、重新打开、后端重启 | 自动进入原生画布；身份为“本地开发者”、项目为“默认工作区”；最终开发用户和项目各 1 条 |
| 退出并刷新、点击进入 | 当前标签页刷新仍为登录页；“进入本地工作区”重新进入 |
| 普通登录模式隔离 | 同一电脑另以 `-RequireLogin` 在回环 8002 启动；浏览器显示普通登录页，已有开发会话 `/team/me` 为 401、`/team/dev-login` 为 404，development 为 false |
| 本机边界 | 实际外部 Host 请求被拒绝 403；远端地址、外部 Origin 和禁用开发模式另由隔离平台测试覆盖；未开放 LAN 监听 |
| 画布、算子库、参数面板 | 选择代表模板、自定义 Pipeline，搜索并添加算子、自动排版、编辑参数、手动连线、保存并重开 |
| 运行前检查 | 无输入、缺模型绑定、未连接节点均有明确提示；修正连接后检查通过 |
| 原始/生成数据集 | 原生导入公开 JSONL 示例，中文内容预览，查看生成草稿、样本和发布 v1 |
| 原生文件与文件夹 | Windows UI Automation 操作真实系统窗口；含中文、空格、盘符和反斜杠的路径正确返回；结果目录选择后取消保留原值 |
| 模型服务 | 空列表、新建表单、必填拦截、未保存编辑保护；取消导航保留输入，确认放弃后可导航；没有保存真实凭证或测试真实 API |
| 模型训练 | 新建并保存“Windows 验收方案（未训练）”，模型为明确 fixture 引用；重启后仍在；未配置 SSH 主机，未执行训练 |
| 人工评测 | 进入原生工作区评测页、空批次状态、草稿/v1 选择和评测人员显示；完整评分领取由离线回归覆盖，未宣称真实人工质量验收 |
| 任务 | 真实运行状态、步骤、算子、耗时、日志、运行历史与最终结果面板均可查看；无真实百分比的流程没有编造百分比或 ETA |
| Vite 开发 | 独立浏览器访问 `npm run dev` 的 `127.0.0.1:5173`，自动登录与 `/team`、`/api` 代理正常 |

真实执行流程为 `Windows 离线验收（无模型）`，任务 `18b3eba2f09e`：公开 `text-one.jsonl` → `PandasOperator`（固定指令、回显原文）→ `RemoveExtraSpacesRefiner`。由本机 Ray 执行两个原生算子，状态 completed，2/2 步，输出 1 条，页面显示执行耗时 00:06；冷启动等待另计。Ray 自动发现本机 GPU 不等于执行了 GPU 训练，此任务为 CPU 文本转换。

页面自动收录到草稿 `ds_1d85638d5dd26fe309ab94649f04f372` 并发布 v1。通过真实下载链接取得 `18b3eba2f09e_final.jsonl`，以 UTF-8 解析，核验 1 条、`id/text/instruction/input/output` 字段、空 input、固定 instruction，以及 output 等于规范空白后的 text。下载内容 SHA-256 为 `90f7cb0b929bb44ae9ffec530aef522875e747d782f8ee81cd48f1a621f113f6`。

后端重启后用浏览器重新查看并用 API 交叉核对：自定义流程仍含两个算子、来源仍在、任务 completed、草稿 1 条、样本 1 条、发布版本 1 条，训练验收方案亦保留。没有清空、重建或删除运行数据库。

## 回归与进程管理

实际运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test-windows.ps1 -Python .\.venv\Scripts\python.exe
pwsh -NoProfile -File scripts/test-windows.ps1 -Python .\.venv\Scripts\python.exe
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test-local.ps1
Push-Location repos\dataflow-webui\backend
try { & ..\..\..\.venv\Scripts\python.exe -X utf8 -m unittest discover -s platform_tests -v }
finally { Pop-Location }
Push-Location repos\dataflow-webui\frontend
try {
    npm test
    if ($LASTEXITCODE -ne 0) { throw 'Frontend tests failed' }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
}
finally { Pop-Location }
```

| 范围 | 结果 |
| --- | --- |
| Core CPU | 165 通过，1 GPU 项按标记排除 |
| WebUI 后端 | 471 通过，3 跳过，7 子测试通过 |
| Windows 平台测试 | 18 通过，含真实小型私有工作进程、UTF-8、文件锁、备份恢复和单调修订时间 |
| PowerShell 5.1 / 7 脚本回归 | 均通过，包含非零退出码、路径空格、失败就绪及旧 PID 拒绝 |
| 前端 Node 22 | 88 通过；生产构建成功，保留上游 Sass 弃用及大分块警告 |
| 论文扩展 | 9 通过；21 项缺少历史 tokenizer 或 SFT2000 回放数据明确跳过 |

后端 3 项跳过为两项无符号链接创建权限的检查，以及仅 Linux 训练 runner 适用的 POSIX 进程组测试；具体原因可用 pytest `-rs` 查看。固定响应的代表流程测试属于回放/隔离验证，不是本轮真实模型 API 执行。

前台关闭后本实例工作进程与 Ray 进程均退出。Daemon / Status / Stop 在完整安装环境实测，停止时记录的 5 个实例进程全部消失，8001 可立即重新绑定并再次启动。另以隔离临时检出记录一个真实无关测试进程的 PID，Stop 拒绝终止它且确认其仍存活，再由测试自身清理。没有关闭无关程序。

## 未运行边界与清理

- **NOT_RUN：真实模型 API 生成、真实模型兼容性和质量。** 没有提供或使用凭证；接下来由使用者按 [模型 API 配置](model-api.md) 在自己的实例配置服务，再运行代表性文本 SFT / DPO 等流程。
- **NOT_RUN：真实 SSH、远程训练、GPU 训练、MinerU / DataFlow-MM 与全部算子覆盖。** 未连接主机、下载权重或安装可选训练环境。
- **NOT_RUN：需要历史 tokenizer / 回放数据的论文实验。** 仓库首次检出无这些资源，对应测试跳过，未当作通过。
- 清理范围限定为本轮临时脚本、测试缓存、下载副本和临时服务；保留 `.venv`、`node_modules`、生产构建和已保存的本机验收运行数据。它们均不进入 Git 提交。未清理系统交换空间或无关项目。

## 交付提交

两个子模块均已先提交并直接推送到 Mau-Q fork 的 main，无强制推送；随后主仓库更新 gitlink 与组件锁。验收后的修复版本为：

| 仓库 | 修复提交 |
| --- | --- |
| Core | `bf48d61bfb57c122136d2a1bd096ed9409cf242a` |
| WebUI | `41549cb0176e59ca4c1508e0c5caaffcc9815889` |

主仓库提交由包含本记录的 Git 历史核对。本记录的实机结果不能代替 CI，也不把 CI 平台夹具当成真实模型执行。
