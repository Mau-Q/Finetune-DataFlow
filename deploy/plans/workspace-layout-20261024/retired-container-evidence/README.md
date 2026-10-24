# 旧 GPU2 / smoke 容器删除回执

- `archive-summary.json`：删除前的逐文件对照、独有文件归档与读回结果；其中 NO_CONTAINERS_REMOVED 是归档阶段的历史状态。
- `removal-result.json`：后续两个容器已删除，最新 GPU1、平台、HTTPS、镜像引用、卷和模型保留验证。
- `unique-files-manifest.json`：91 个独有文件的路径、大小和 SHA-256；不包含文件正文、私有配置或凭据。
- `audit-manifest.json`：上述紧凑回执和实际执行脚本的哈希。

完整配置、完整上层文件清单、归档及日志只在学校私有目录保留：`runs/maintenance/2026-10-24-retired-containers/`。公开紧凑清单不替代完整归档。

详细步骤与当前状态见 [删除记录](../../../../docs/maintenance/retired-training-containers-20261024.md)。
