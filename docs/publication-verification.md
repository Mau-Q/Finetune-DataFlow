# 公开源码整理验证记录

日期：2026-10-20。版本由 [组件清单](../locks/components.json) 固定。

## 本地验证

| 检查 | 结果 |
| --- | --- |
| `./scripts/test-local.sh`：Core CPU | 163 passed，1 deselected（GPU 标记） |
| 同脚本：WebUI backend | 404 passed，另有 7 subtests passed |
| 同脚本：paper-dataflow | 30 passed |
| 前端 Node 契约测试 | 26 passed |
| 本机前端构建 | 通过 |
| 干净 WebUI checkout，使用发布锁文件 `npm ci` 后构建 | 通过 |
| 空 Python 3.12 环境的 `uv pip install --dry-run` | 成功解析 271 个依赖 |
| 组件清单 / gitlink / URL / 跟踪边界检查 | 通过 |
| 新入口文档本地链接、shell 语法和 Git diff 空白检查 | 通过 |
| Gitleaks 8.30.1：根仓库历史和待发布文件 | 通过；精确豁免一个已核对的 tokenizer SHA-256 误报 |
| Gitleaks：Core 待推送提交与 WebUI 历史 | 通过 |

发布准备修复了 Core 将 `.DS_Store` 视为模块导入的问题，添加非模块文件和空目录回归；WebUI 纳入此前只在本机存在的 npm 锁文件，支持干净克隆后执行 `npm ci`。

## 范围与限制

Python 检查使用现有工作环境执行完整回归；空环境只做依赖解析，没有重新下载并安装全部 Python 依赖。Core 的 GPU 测试未运行，未调用真实文本/视觉 API，未重新验证 MinerU 或独立 MM 推理，也未评估生成数据质量或训练收益。

前端构建存在上游 Sass 废弃 API 和产物体积提示；Python 回归仍有上游废弃 API、未知测试标记等警告，均未阻止本次检查。验证环境为 macOS Apple Silicon；GitHub Actions 的 Linux 结果以仓库实际运行状态为准。
