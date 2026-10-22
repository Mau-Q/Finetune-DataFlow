# DataFlow WebUI

本 fork 用于本地与局域网的数据生成、来源追溯、人工评测、发布与导出。界面沿用 DataFlow 原生画布、资源列表和参数控件。

产品内的 Agent 聊天、Agent 子进程和 MCP 入口已按用户要求移除。当前使用方式是浏览器和 REST API。仓库开发技能与 AGENTS.md 属于源码维护工具，不会在产品中运行。

- 集成部署入口：父仓库 `scripts/start-lan.sh`。
- 局域网账号、HTTPS、权限与数据迁移：父仓库 `docs/lan-usage.md`。
- 规格与验收：父仓库 `docs/lan-collaboration-data-review-spec.md`、`docs/lan-implementation.md`。
- 后端：`backend/README.md`；前端构建：`cd frontend && npm run build`。

本机开发推荐使用 [Finetune-DataFlow 集成仓库](https://github.com/Mau-Q/Finetune-DataFlow) 的固定子模块与安装脚本。每位开发者独立运行自己的实例，Windows 使用根目录 `.venv`，执行 `scripts/setup-windows.ps1` 后运行 `scripts/webui-windows.ps1 -Action Foreground`，地址为 `http://127.0.0.1:8001/`。macOS 使用集成仓库 `scripts/setup.sh` / `scripts/webui.sh`。

本机入口明确开启开发自动登录，以独立的“本地开发者”进入“默认工作区”；普通登录使用 Windows `-RequireLogin` 或集成仓库 `scripts/dev.sh --require-login`。身份、权限、CSRF 与数据归属仍由网关管理。只有本机开发模式使用原生文件选择器，LAN 保留浏览器上传与主机路径限制。完整 Windows 安装、无模型流程及实机边界见集成仓库 `docs/windows-development.md` 和 `docs/windows-acceptance.md`。

前端热更新：在 `frontend` 运行 `npm ci`、`npm run dev`；Vite 的 `/team`、`/api` 默认代理到本机 `8001`。Windows 使用 Node.js 22/npm；运行后端测试前设置 `$env:PYTHONUTF8='1'`，避免系统默认编码影响中文夹具。共享资源修订时间在持锁保存时单调递增，防止粗粒度系统时钟使旧编辑覆盖保护失效。

下方为上游 Harness 的历史说明，保留开发背景。其中 Agent/MCP 产品运行方式已经失效，不适用于本 fork 当前部署。

<details>
<summary>上游历史说明</summary>

# DataFlow-Harness

[![](https://img.shields.io/github/repo-size/OpenDCAI/DataFlow-WebUI?color=green)](https://github.com/OpenDCAI/DataFlow-WebUI)
[![Technical Report](https://img.shields.io/badge/Technical%20Report-arXiv%3A2607.16617-B31B1B?logo=arxiv&logoColor=white)](https://arxiv.org/pdf/2607.16617)

中文文档：**[README_zh.md](README_zh.md)**

Build, run and manage [DataFlow](https://github.com/OpenDCAI/DataFlow) data pipelines with a coding agent — through a visual canvas, through MCP, or with skills alone.

## Names you will see

| Name | What it refers to |
|---|---|
| **DataFlow** | The upstream data-processing framework ([OpenDCAI/DataFlow](https://github.com/OpenDCAI/DataFlow)). Installed as the `open-dataflow` package. Not this repo. |
| **DataFlow-Harness** | The system this repo builds: skills + MCP + WebUI working together. The name of the product, and of the paper. |
| **DataFlow-WebUI** | The repository name, and the visual-canvas layer specifically. Kept for URL stability. |
| **`DataFlow-WebUI-<version>.zip`** | A release package with the frontend pre-built, for running without a clone. See [docs/RELEASE-PACKAGE.md](docs/RELEASE-PACKAGE.md). |

This repo ships **three independent layers**. Install only the one you need.
They are independent at install and runtime; internally, all agent variants are
rendered from the same `skills/canonical/` source so the standalone and
MCP-aware instructions cannot drift.

## Which layer do I want?

| | `webui` | `harness` | `skills` |
|---|---|---|---|
| **You get** | Visual DAG canvas + backend + MCP | Backend + MCP, no browser UI | Agent skills only |
| **You need** | Python 3.10+, Node 20+ | Python 3.10+ | Python 3.9+ (to render the skills) |
| **Installs packages** | yes (uv + npm) | yes (uv) | **no** |
| **Runs a server** | yes, port 8000 | yes, port 8000 | **no** |
| **Agent writes pipelines** | ✅ | ✅ | ✅ |
| **Agent sees live operator registry** | ✅ | ✅ | ✗ (uses bundled reference) |
| **Pipelines appear on a canvas** | ✅ | ✗ | ✗ |
| **Install time** | minutes | ~1 min | seconds |

The `skills` profile installs no packages, but it does run a Python script to
render the skill files, so Python 3.9+ must be present.

**30-second decision:**

- You want to *see and edit* pipelines as a graph → **`webui`**
- You drive everything from Claude Code / Codex / Cursor and never open a browser → **`harness`**
- You just want your agent to write correct DataFlow code, with no server → **`skills`**

```bash
git clone https://github.com/OpenDCAI/DataFlow-WebUI.git
cd DataFlow-WebUI

./install.sh --list                  # compare the three, in detail
./install.sh --profile skills        # or harness, or webui
```

Every profile supports `--check` (prerequisites only), `--dry-run` (show the plan, change nothing) and `--uninstall`.

Full per-layer guides: **[webui](docs/profiles/webui.md)** · **[harness](docs/profiles/harness.md)** · **[skills](docs/profiles/skills.md)**

## For agents setting this up

If an AI coding agent is configuring this repository, point it to
**[docs/agents/SETUP.md](docs/agents/SETUP.md)** before running installation.
That guide defines the authorization boundaries, exact commands, verification
steps, and actions that require human approval.

## Installation and usage

The `webui` profile installs the complete browser-based stack. Run the commands
below from the repository root and use the same activated environment for setup
and startup. Python **3.10 is recommended and is the minimum supported version**.

### Install prerequisites

You need Git, Python 3.10+, and Node.js 20+ (which includes npm) for the `webui` profile. The `harness` profile needs Python 3.10+ only. The `skills` profile needs Python 3.9+ only (no packages installed). The installer will offer to install `uv` (the recommended Python package manager) if missing; you can also install it manually or use `--pip` to fall back to pip.

| System | Python and Git | Node.js 20+ and npm | uv (optional — installer can add it) |
|---|---|---|---|
| macOS | `brew install python@3.10 git` | `brew install nvm` then `nvm install 20` | `brew install uv` |
| Ubuntu/Debian | `sudo apt update && sudo apt install -y python3.10 python3.10-venv git` | [nvm](https://github.com/nvm-sh/nvm), then `nvm install 20` | [uv installer](https://docs.astral.sh/uv/getting-started/installation/) |
| Windows | `winget install Python.Python.3.10 Git.Git` | `winget install OpenJS.NodeJS.LTS` | [PowerShell installer](https://docs.astral.sh/uv/getting-started/installation/) or let the installer add it |

On macOS/Linux, the uv installer is:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

On Windows PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Restart the terminal after installing tools, then verify:
- `python --version` (or `python3 --version`)
- `node --version` (must be 20 or newer, only for `webui`)
- `npm --version` (only for `webui`)
- `uv --version` (optional — the installer will offer to add it if missing)

### Create and activate a Python environment

Choose **one** of the following; do not mix environments.

```bash
# venv (macOS/Linux; Windows PowerShell uses .venv\Scripts\Activate.ps1)
python3.10 -m venv .venv
source .venv/bin/activate

# Or conda (all systems)
conda create -n dataflow python=3.10 -y
conda activate dataflow
```

On Ubuntu/Debian, install `python3.10-venv` if `venv` reports that `ensurepip`
is missing.

**On Windows**, the install script (`.sh` files) must be run through **Git Bash** (bundled with Git for Windows). Do not run `.sh` files in PowerShell or `cmd.exe` — they will not execute. After installing Git for Windows, open **Git Bash** from the Start menu or right-click in the repository folder and select "Git Bash Here", then run:

```bash
# In Git Bash (Windows) or any terminal (macOS/Linux)
./install.sh --profile webui
```

If you activated a conda environment in PowerShell before opening Git Bash, the environment carries over. Otherwise, ensure the Python you want is on PATH or set `DF_PYTHON=python` (or `DF_PYTHON=/c/path/to/python.exe`) before running `./install.sh`.

### Install, start, and use

```bash
./install.sh --profile webui
./scripts/start.sh             # foreground; Ctrl+C stops it
# or: ./scripts/start.sh --daemon
```

**Windows users**: run these commands in **Git Bash**, not PowerShell or cmd.exe.

Open <http://localhost:8000/>. In the chat panel select an installed agent,
describe the pipeline you want, and inspect the resulting DAG on the canvas.
Check or stop a background server with `./scripts/start.sh --status` and
`./scripts/start.sh --stop`.

The installer uses `uv` by default (faster, more reliable). If `uv` is not installed, the installer will offer to install it automatically. To use `pip` instead, pass `--pip`:

```bash
./install.sh --profile webui --pip
```

### Configure an AI agent

The WebUI chat workflow requires at least one supported agent. Install and
authenticate an agent, then explicitly configure its MCP connection:

```bash
# Claude Code
curl -fsSL https://claude.ai/code/install.sh | sh
export ANTHROPIC_API_KEY=sk-ant-...
./install.sh configure-agent --agent claude

# Codex (API key or `codex login` OAuth)
npm install --global @openai/codex
codex login                         # OAuth, or export OPENAI_API_KEY=sk-...
./install.sh configure-agent --agent codex

# Cursor: install the IDE, open this repository, then:
./install.sh configure-agent --agent cursor
```

Agent configuration is intentionally a separate step from installation. The
installer does not write API keys. See [Agent setup](docs/agents/SETUP.md) for
the exact authorization boundaries and verification steps.

## Installing never writes agent configuration

Installing and configuring an agent are two separate commands, on purpose:

```bash
./install.sh --profile harness                      # installs; writes no agent config
./install.sh configure-agent --agent claude         # project-scoped, shows a diff first
./install.sh configure-agent --agent codex --scope user   # asks before writing ~/.codex/
```

Installing **never writes MCP configuration**, in either scope. That is
`configure-agent`'s job.

### Where the skills land, per agent

`--scope` only affects Claude Code. The other two agents read from the repo, so
their assets are always installed here:

| Agent | Installed to | Available in | Verify |
|---|---|---|---|
| **Claude Code** | `./.claude/skills/` (default), or `~/.claude/skills/` with `--scope user` | this repo, or every project with `--scope user` | `/generating-dataflow-pipeline` appears in completion |
| **Codex** | `./AGENTS.md` + `./.codex/skills/` in this repo | this repo only — Codex reads `AGENTS.md` from the directory it starts in | open `AGENTS.md`; it routes to `.codex/skills/` |
| **Cursor** | `./.cursor/skills/` and `./.cursor/rules/` in this repo | this repo only, when opened as a project in Cursor | rules appear under Settings → Rules |

There is no global install for Codex or Cursor — both are directory-scoped by
design. `--scope user` does not change that.

Each profile declares the paths it must not touch, and the installer fingerprints
them before and after the install and fails if any changed. Anything it cannot
prove it wrote is never overwritten without `--force`.

Existing MCP servers in your config are merged, never overwritten. No API keys are read, written or logged.

Upgrading from `scripts/setup_all.sh`? See [docs/migration/from-setup-scripts.md](docs/migration/from-setup-scripts.md).

## What DataFlow-Harness is

DataFlow-Harness combines **skills** (procedural knowledge about operator selection, schema links and assembly order), **MCP** (a live connection to the operator registry and current pipeline state), and the **WebUI** (turning agent-built workflows into persistent, editable DAGs).

<p align="center">
  <img src="https://github.com/user-attachments/assets/c54d92ea-a6d5-4c3c-8144-87c3cdfee276" alt="DataFlow-WebUI" width="90%">
</p>

*The dual-modality interface: conversational agent and visual DAG editor stay in sync.*

<p align="center">
  <img width="1280" height="638" alt="DataFlow-Harness architecture" src="https://github.com/user-attachments/assets/d9c862ac-a1a2-42b1-9f07-440d20d59d8f" />
</p>

*A shared pipeline representation synchronized across the agent runtime and the WebUI. Skills guide construction; the validation engine checks DAG structure and schema compatibility.*

### Why it helps

**Bridges the NL2Pipeline gap.** Natural-language intent becomes a persistent, platform-native pipeline artifact you can inspect, edit, run and reuse.

**Procedural knowledge, not just tool lists.** Building a VQA dataset from textbooks needs PDF parsing, layout understanding, OCR, image-text alignment, QA extraction and quality filtering *in the right order*. That ordering knowledge is what the skills encode.

**Reusable workflows.** Data preparation becomes reusable pipelines rather than one-off scripts.

**Reported results.** The DataFlow-Harness paper reports a 93.3% end-to-end pass
rate on a 12-task data-engineering benchmark, with 72.5% lower cost and 49.9%
lower generation latency than vanilla Claude Code.

Those figures come from the paper's own harness and are **not reproducible from
this repository** — the benchmark tasks, run configuration and raw results are not
included here. Treat them as published findings, not as a claim you can verify by
installing this repo. Details and methodology: [DataFlow-Harness](https://huggingface.co/papers/2607.16617).

## Supported agents

| Agent | Mode | MCP config | Auth |
|---|---|---|---|
| **Claude Code** | WebUI-dispatched, or in your terminal | `.mcp.json` (project) | `ANTHROPIC_API_KEY`, or `ANTHROPIC_BASE_URL` for a gateway |
| **Codex** | WebUI-dispatched, or in your terminal | `~/.codex/config.toml` | `OPENAI_API_KEY` (+ optional `OPENAI_BASE_URL`), or `codex login` OAuth |
| **Cursor** | IDE only — not dispatched by the WebUI | `.cursor/mcp.json` (project) | Cursor built-in |

Cursor is used by opening this project in the IDE; its agent discovers the MCP server and pushes pipelines onto the canvas. It is not driven from the WebUI chat panel.

## Architecture and decisions

- [Component boundaries](docs/architecture/overview.md) — how the three layers depend on each other
- [ADR-001: single source of truth](docs/architecture/adr-001-source-of-truth.md) — why skills live in one repo
- [ADR-002: one package manager](docs/architecture/adr-002-package-managers.md) — npm vs Yarn, resolved
- [ADR-003: install/configure split](docs/architecture/adr-003-install-configure-split.md) — why installing writes no agent config
- [Branch audit](docs/architecture/branch-audit.md) — status of every remote branch

## Contributing

Skills are edited in `skills/canonical/` only. The files under `.claude/skills/`,
`.cursor/skills/`, `.cursor/rules/<skill>.mdc`, `.codex/skills/` and `AGENTS.md`
are generated build output and are **not tracked in git** — a fresh clone will not
have them:

```bash
make skills      # generate agent assets from skills/canonical/
make check       # run every static check CI runs
```

CI regenerates and diffs, so a hand-edited generated file fails the build.

## Citation

If you use the DataFlow-Harness platform, its agent workflow, MCP integration,
or editable pipeline interface, cite the DataFlow-Harness paper:

```bibtex
@article{he2026dataflow,
  title={DataFlow-Harness: A Grounded Code-Agent Platform for Constructing Editable LLM Data Pipelines},
  author={He, Runming and Wong, Zhen Hao and Liang, Hao and Meng, Zimo and Shen, Chengyu and Ma, Xiaochen and Zhang, Wentao},
  journal={arXiv preprint arXiv:2607.16617},
  year={2026}
}
```

If you use or cite the underlying DataFlow framework, cite the DataFlow paper:

```bibtex
@article{liang2025dataflow,
  title={DataFlow: An LLM-Driven Framework for Unified Data Preparation and Workflow Automation in the Era of Data-Centric AI},
  author={Liang, Hao and Ma, Xiaochen and Liu, Zhou and Wong, Zhen Hao and Zhao, Zhengyang and Meng, Zimo and He, Runming and Shen, Chengyu and Cai, Qifeng and Han, Zhaoyang and others},
  journal={arXiv preprint arXiv:2512.16676},
  year={2025}
}
```

## Community

<p align="center">
  <img src="https://github.com/user-attachments/assets/b958dc89-d76e-4e47-9277-22b3f6661944" alt="DataFlow community QR code" width="85%">
</p>

Licensed under Apache 2.0 — see [LICENSE](LICENSE).

</details>
