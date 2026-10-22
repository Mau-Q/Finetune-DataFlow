# 原始数据集本地示例

五种列表数据形式均使用真实本地文件，通过普通导入接口保存平台副本；前端没有内置示例内容。

| 数据集名称 | 原文件 | 数量 |
| --- | --- | --- |
| PDF（示例） | `shapes.pdf` | 1 个文件，1 页说明与图形 |
| 图片（示例） | `shapes.png` | 1 张图片，1080 × 420 |
| 文本（示例） | `shapes.txt` | 1 个 UTF-8 文本文件 |
| 结构化数据（示例） | `shapes.csv` | 3 条记录，不含表头 |
| 混合（示例） | `shapes.pdf` + `shapes.png` | 2 个文件 |

内容围绕红色正方形、蓝色圆形、绿色三角形，人工编写用于展示文件管理。CSV 字段为 `id,shape,color,sides,position`。这些是原始材料，尚未执行生成 Pipeline 或整理为训练样本。

在启动本地服务后运行：

```bash
python examples/sources/import_examples.py http://127.0.0.1:8000
```

脚本从自身目录读取文件，保存受管副本，并逐文件下载核对 SHA-256 与预览数量。再次运行会核对并复用已有同名数据集；发现同名内容冲突时停止，不覆盖。PDF 和混合集合复用同一材料副本；示例源文件不会被移动。

PDF 与 PNG 已随源码保存，不需要额外生成依赖。需要重新生成时，使用安装有 Pillow 和 ReportLab 的 Python：

```bash
python examples/sources/generate_files.py --font /path/to/chinese-font.ttf
```

PDF 嵌入字体，PNG 由几何图形绘制而成。导入后修改源文件不会自动更改平台中的副本。
