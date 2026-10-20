# 开发与验证

先分别检查根仓库和相关子模块的 `git status --short --branch`，保留他人或先前任务的修改。根目录遵守 `AGENTS.md`，WebUI 另有其 `CLAUDE.md` 约定。

## 固定与更新组件

子模块保存各自 Git 历史。更改组件后先在组件内提交并推送到自己的 fork，再更新根仓库 gitlink 和 `locks/components.json`。不要把提交推送到 `OpenDCAI` 上游。普通克隆使用固定提交，无需追踪组件某条浮动分支。

```sh
python3 scripts/check-workspace.py
git submodule status
git diff --submodule=short
git diff --check
```

版本检查只验证提交、URL 和跟踪边界，不代替 `git status` 对未提交改动的检查。已有工作区的安装脚本不会自动回滚子模块以满足版本固定。

## 回归

```sh
./scripts/test-local.sh
cd repos/dataflow-webui/frontend
node --test src/hooks/dataflow/*.test.mjs
npm run build
```

完整本地脚本依次运行 Core CPU 测试、WebUI 后端与本地扩展测试；Core 排除 `gpu` 标记。测试环境为 `.venvs/dataflow`。CI 执行组件与仓库边界检查，以及前端契约测试和构建，尚未代替完整后端回归。

对持久化或页面行为的修改还应在隔离数据下验证保存、重开、运行拦截、下载和媒体引用。变更数据库前保留一致性备份；真实 API、用户原始材料和正在运行的任务不用于自动冒烟测试。

## 发布边界

发布前审查暂存 diff、组件 outgoing commits、文档链接与密钥扫描。公开源码包含历史实验脚本与快照，不能携带密钥、原始材料、运行数据库、模型权重、缓存或个人输出。`.gitignore` 不会移除已经跟踪的文件；`scripts/check-workspace.py` 对关键运行目录执行额外跟踪边界检查。

根仓库 `.gitleaks.toml` 只为一个固定 tokenizer SHA-256 设置精确误报豁免，不豁免任意 `api_key` 字段或整个源码目录。子模块沿用上游历史；本次发布应重点审查新增或待推送内容，不改写上游历史。
