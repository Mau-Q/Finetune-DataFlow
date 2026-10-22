# 原始材料与训练数据集（M1）

文中的 `DATAFLOW_WORKSPACE` 指 Finetune-DataFlow 集成仓库根目录；这些集成脚本不属于独立 WebUI 检出。执行前设置该环境变量为实际路径。

侧栏提供「原始数据集」和「生成数据集」两个入口，分别对应 `/#/m/materials` 和 `/#/m/training-datasets`。旧 DataFlow Hub、输入数据集和 Pipeline 保留原有入口与注册语义。

## 原始材料

1. 点击原始数据集页「添加数据集」，或原画布「数据集 → 添加」，选择 PDF / 图片并填写名称。平台保存文件副本并生成兼容的输入清单。
2. 在全宽列表点击数据集名称进入详情，切换文件并预览 PDF / 图片。已有 JSON / JSONL / CSV / Parquet 也可通过同一表单单独添加。
3. 新上传文件的分组、来源、说明及解析产物关系在「编辑文件信息」中按需展开；后台仍保留本地路径登记 API。

第一批支持 PDF、PNG、JPEG、WebP、GIF、BMP；公式、表格通过这些原文件或解析后的图片管理。此阶段不运行解析、不新建公式或表格编辑器，不接受任意解析格式。PDF 需能解析且未加密；图片按实际格式检查，不能仅改扩展名。每份上限 100 MiB。

不同内容即使文件名相同也使用不同 ID 和存储路径。相同字节内容会提示已存在的材料，不静默覆盖。文件访问按 ID 查找并校验哈希，缺失或内容变化会报错。

## 训练数据集草稿

1. 创建草稿，分别选择模态（文本 / 图文）与训练类型（SFT / DPO）。
2. 选择 UTF-8 JSON 数组文件或逐行 JSONL 文件导入，上限 20 MiB。
3. 查看字段集合、每页 20 条的原始样本预览、图片预览和导入记录。

支持两种基本 SFT 形状，保留原始字段及额外字段，不自动映射或改写正文：

```json
[{"instruction": "问题", "input": "可选上下文", "output": "答案"}]
```

```json
[{"messages": [{"role": "user", "content": "问题"}, {"role": "assistant", "content": "答案"}]}]
```

`instruction`、`output` 必须为非空字符串；`input` 存在时必须为字符串。`messages` 必须含 user 和 assistant 消息；支持 system、user、assistant、tool 角色，内容为非空文本或 text / image_url 内容块。这里只检查基本结构，不评价答案质量，不执行任意 JSON Schema。

图文样本必须包含图片引用，文本样本不能含图片引用。支持 `image` 字符串、`images` 字符串数组，或 messages 中的 `image_url` 内容块：

```json
[{"instruction": "图中是什么？", "output": "一张图表。", "images": ["images/chart.png"]}]
```

先通过原始数据集入口导入图片，再在生成数据集的导入对话框中为每个引用选择图片；高级入口仍支持明确的 JSON 映射（将示例 ID 换为实际图片 ID）：

```json
{"images/chart.png": "mat_0123456789abcdef0123456789abcdef"}
```

不会根据同名文件搜索路径，也不会下载远程 URL。即使引用写成 URL，也必须显式绑定已导入的图片。相同草稿内，同一引用不能重新绑定另一张图；已有映射可供后续批次复用。缺少映射、文件缺失、哈希改变、引用 PDF 而非图片都会阻止导入。

全批结构与媒体检查通过后一次写入；失败提示第几条样本，已有草稿不变。重复文件内容会拒绝；批次内或与已有样本完全相同的 JSON 对象会跳过，并报告数量。仅对象字段顺序不同仍视为重复；含不同额外字段则是不同样本。每次有效导入保存规范化内容哈希、原文件哈希、文件名与新增/跳过数量。

当前已提供创建、导入、预览、样本编辑、发布冻结和数据/媒体打包导出。编辑与发布步骤见 [任务与发布说明](text-generation-and-releases.md)。DPO 使用 `prompt/chosen/rejected` 字符串字段，支持文本或附带图片引用的图文样本。

## 存储、备份与 API

当前权威存储为 `backend/data/datasets.sqlite3`。原始数据集、材料、草稿、样本、媒体关联和发布元数据统一进入 SQLite；PDF、图片、清单和发布包继续作为本地文件保存。旧 YAML / JSON 元数据保留为一次性迁移来源，不再作为实时第二数据库。

数据库、自动备份、恢复命令和验证范围见 [数据集 SQLite 存储说明](dataset-storage.md)。

`DatasetRegistry` 保留原 API 和数据集 ID，不扫描材料目录；通过原始数据集导入表单添加 PDF / 图片时，由薄适配登记输入清单。已有注册记录保留，不做全量迁移。

API 前缀为 `/api/v1/library`，使用现有 ApiResponse 封装。业务失败在应用中通常仍返回 HTTP 200，调用方需检查 `success` 及 `meta.http_status`：

| 操作 | 路径 |
| --- | --- |
| 材料列表 | GET `/materials` |
| 上传材料（file + metadata JSON 字符串） | POST `/materials/upload` |
| 登记本地路径（JSON body） | POST `/materials/register` |
| 材料详情 / 完整更新元数据 | GET / PUT `/materials/{id}` |
| 原文件 / 浏览器预览 | GET `/materials/{id}/file` |
| 草稿列表 / 创建 | GET / POST `/drafts` |
| 草稿详情与分页 | GET `/drafts/{id}?offset=0&limit=20` |
| 导入训练文件（file + media_bindings JSON 字符串） | POST `/drafts/{id}/import` |

开发验证：从 backend 执行 `python -m pytest tests/test_data_library.py -q`；前端执行 `npm run build`。工作区完整回归入口为 `${DATAFLOW_WORKSPACE}/scripts/test-local.sh`。

## 数据集入口与精简视图（2026-10-19 更新）

当前侧栏名称为「原始数据集」和「生成数据集」，路径保持不变。

- 原画布「数据集 → 添加」与原始数据集页右上角「添加数据集」共用导入表单。名称可自动填写；PDF / 图片可多选，JSON / JSONL / CSV / Parquet 每次添加一份。
- PDF / 图片保存为材料副本，并生成含 `source` / `source_name` / `material_id` 的 JSONL 输入清单，登记到兼容的 DatasetRegistry。可以在原画布中选择；这不代表对应 Pipeline 已经运行，也不保证任意算子接受所有模态。
- 原始数据集页默认只显示全宽列表；点击名称或「查看」进入详情，PDF / 图片可逐份切换。新上传文件的名称、分组、来源、关联关系等编辑入口折叠在「编辑文件信息」中；旧注册文件保持原有输入信息。后台材料管理 API 仍保留，包括本地路径登记。
- 生成数据集页默认只显示全宽列表；进入详情后以摘要列表展示样本，点击样本展开问题、回答、上下文和图片；新建与导入使用按需打开的对话框。图文文件会提取图片引用，通过下拉框选择材料，手动 JSON 映射作为高级入口保留。
- ID、哈希、完整路径、字段列表和导入记录收在「数据集详情」里；原始 JSON 收在每条样本的「查看原始数据」里。信息和数据没有被删除。

显示偏好保存在 `backend/data/dataset_visibility.json`（沿用 BASE_DIR / RESOURCE_DIR），结构为 `hidden_dataset_ids` 与 `hidden_draft_ids` 两个 ID 数组。仅隐藏指定记录；后来新增的记录默认可见。清除对应数组中的 ID 可以恢复显示。该文件是本地运行配置，不提交到源码仓库。

`GET /datasets/` 仍返回全部记录，并增加 `is_visible` 和 `type` 字段；`?visible_only=true` 返回可见子集。画布的数据选择列表与原始数据集页使用相同偏好，但加载历史 Pipeline 仍能解析完整数据列表。`GET /library/drafts?visible_only=true` 对生成数据集应用相同规则，按 ID 读取不受隐藏影响。

新增桥接接口：

- POST `/api/v1/library/inputs/upload`：`files` 多文件 + `name`；单份最多 100 MiB，一批最多 100 份 / 200 MiB。重复整批或同批重复内容明确报错。
- GET `/api/v1/library/inputs/{id}/preview?offset=0&limit=20`：分页预览原始输入；读取失败明确报错。
- GET `/api/v1/library/inputs/{id}/file?row=0`：只从已登记的数据集记录定位 PDF / 图片原件；新材料校验保存时的哈希。

旧的结构化文件上传也改用独立目录，同名上传不再覆盖已有文件。

两个入口均通过 `?dataset=<id>` 打开数据集详情，支持直接访问、刷新和浏览器前进后退；顶部面包屑返回列表，同一页面会保留搜索词及列表滚动位置。进入列表不自动选中或预览第一个数据集。导入、文件预览、样本编辑与发布继续复用已有组件。

## DPO 本地文件示例

`examples/dpo/text.jsonl` 和 `examples/dpo/image.jsonl` 各包含 3 条偏好对，图文文件通过相对路径引用 `examples/dpo/images/shapes.png`。运行该目录的 `import_examples.py`，通过标准材料上传、草稿创建与文件导入 API 登记为「文本 DPO（示例）」和「图文 DPO（示例）」。页面从普通草稿接口读取磁盘数据，示例文件不再打包进前端代码。重复导入脚本会核对现有内容，不重复创建或覆盖已有数据。

DPO 草稿复用样本编辑、版本发布、JSONL 与媒体打包下载；`chosen` 与 `rejected` 必须非空且不同。图文样本必须显式绑定图片材料。SFT 的字段映射、Alpaca 导出与文本生成产物收集不会应用于 DPO；版本派生保留训练类型。导入是保存独立副本，之后修改原始示例文件不会自动改写已导入草稿。

文本生成向导的输入下拉框仅列出内容类型为纯 PDF、存储为 JSONL 文件清单的可见数据集；图片、混合集合和普通结构化记录不出现在选项中。后端提交时的逐份 PDF 校验保留。


## 列表字段与详情（2026-10-19）

- 原始列表：数据集名称、数据形式、数量、更新时间、查看入口。数据形式按实际内容显示 PDF / 图片 / 文本 / 结构化数据 / 混合；PDF 清单仍显示为 PDF，JSONL 等底层格式收进详情。数量带单位，CSV 只计数据记录（不含表头），Parquet 按实际行数计数。
- 生成列表：数据集名称、数据类型（文本/图文 × SFT/DPO）、样本数、最新发布版本、更新时间、查看入口。一个 DPO 偏好对计为一条样本。版本来自 SQLite 中的真实发布记录；没有发布记录时显示「未发布」，发布后仍可继续编辑草稿。
- 两个列表默认按最近更新时间排序；旧记录缺少更新时间时以已记录的创建/登记时间作为排序后备，但时间单元格显示「未记录」，不把历史登记时间冒充更新时间。新原始登记保留首次登记及创建时间，更新记录时单独写入更新时间。
- 详情按需展开基本信息、结构与来源、导入记录、存储信息。受管原始文件可查看 MIME、大小、页数/尺寸、材料关系、来源、时间、父材料 ID、受管文件名和 SHA-256；文件编辑入口保留。生成详情展示字段、模态、训练类型、来源任务及源发布版本（有记录时）、图片引用数；已发布版本的下载与哈希仍在「整理与发布」中。
- 现有数据集名称及样本内容保持原样，名称中的「（示例）」继续保留。没有保存的描述、来源和时间显示「未填写」或「未记录」。

相关验证：`python -m pytest tests/test_source_datasets.py tests/test_training_lifecycle.py tests/test_data_library.py tests/test_dataset_registry.py tests/test_dataset_database.py -q`；前端运行 `node --test src/views/manage/library/catalog.test.mjs`、相关文件 ESLint 及 `npm run build`。

## 五种原始数据集示例

`examples/sources/` 保存 PDF、PNG、UTF-8 TXT 与 CSV 实体文件；`import_examples.py` 通过普通 API 添加「PDF（示例）」「图片（示例）」「文本（示例）」「结构化数据（示例）」「混合（示例）」。数量分别为 1 个文件、1 张图片、1 个文件、3 条记录、2 个文件。混合集合包含 PDF 与 PNG，不代表存在统一执行所有格式的 Pipeline。

导入表单新增 TXT / Markdown 文件支持，按一份文档计数并保留全文与换行，详情提供正文预览与原文件下载。PDF / 图片仍可批量导入，单份文本/结构化文件按文档或记录管理，批量混合选择统一按文件集合管理。示例详情、文件哈希和重复运行行为见 [原始示例说明](../examples/sources/README.md)。

## 文件夹导入

「添加数据集」提供一个「选择文件或文件夹」入口与统一拖入区域，不需要先选择导入模式。macOS 系统选择窗口允许同时选择文件及文件夹；文件夹递归扫描 PDF、PNG/JPEG/WebP/GIF/BMP、TXT/Markdown、JSON/JSONL/CSV/Parquet，显示识别结果与跳过清单；隐藏目录/文件、`__MACOSX` 和不支持的格式跳过。导入上限沿用每个文件 100 MiB、每次 100 个有效文件 / 200 MiB。

`POST /api/v1/library/inputs/upload-folder` 接受多份 `files` 与 `name`，文件名使用原相对路径。平台将 PDF/图片保存为受管材料，文本/结构化文件保存为受管副本，通过同一输入清单组织成员，并在 SQLite 保存成员关系。文件目录结构以相对路径标签保留，实际文件以独立身份保存，子目录同名文件不会互相覆盖。多个类别显示「混合」，同一类别仍显示 PDF、图片、文本或结构化数据；数量按成员文件计，进入成员预览后再看记录。自动识别不会自动执行 Pipeline。

详情可切换 PDF/图片/文本/结构化成员；`GET /inputs/{id}/member-preview?row=0` 预览选中文本全文或结构化文件前 20 条记录，原文件可完整打开/下载。文件夹内容导入前验证，失败时事务回滚并清理本轮新增副本；再次导入相同相对路径及内容会拒绝重复。不扫描磁盘其他目录，也不会跟随清单内容自动导入额外文件。


统一系统选择由 `POST /inputs/choose-local` 返回短期选择标识、自动名称、分类及跳过清单；`POST /inputs/import-local` 按该标识保存副本。服务器只读取系统窗口中明确选择的文件或目录，不接受客户端提供任意本地路径；选择 15 分钟过期，导入前检查文件是否变化，导入后标识不可重复使用。原生选择器在 macOS 使用系统 NSOpenPanel；其他系统仍可统一拖入文件/文件夹，点击入口回退为浏览器文件选择。目录符号链接和隐藏内容跳过。


## 画布中的原始数据集选择

画布工具栏与弹窗统一称为“原始数据集”。弹窗使用与原始数据集页面一致的可见数据源、数据形式和数量规则，按更新时间排列，支持搜索与形式筛选；列表仅显示名称、形式、数量及查看/选择操作。详情可切换原文件、预览 PDF/图片/文本/结构化记录、翻页和查看属性，不修改画布配置；点击选择才沿用原有数据集 ID 加入画布。添加入口复用统一文件/文件夹导入组件。弹窗不包含生成数据集或 Text2SQL 管理页签，Text2SQL 底层功能保留。

本地 `backend/data/dataset_visibility.json` 的 hidden_dataset_ids、hidden_draft_ids 控制数据集列表可见性；hidden_prompt_ids 控制 Prompt Manager 中的展示。隐藏不删除记录、文件、发布版本或任务快照，按 ID 读取及已有引用仍可用。此文件属于本地展示偏好，不提交到代码仓库。
