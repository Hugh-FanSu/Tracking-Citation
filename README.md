# Tracking Citation

版本：**0.8.0**。支持Mac/Windows共用源码；[安装与双平台发布流程](docs/platform-releases.md)。Windows完整解析尚待实机验证。

源码安装：`python -m pip install ".[full]"`，启动图形界面：`paper-citations-gui`。

把原始论文 PDF 转为原始 TEI、阅读 Markdown、引用证据 JSON，并可填入用户自己的 Excel 模板。
支持指定被引机构或个人作者、本地别名清单、本地报告清单和模板字段映射。机器输出是候选关系，不把“表格已填写”当作“引用已确认”。

## 首页三步与异常日志（0.7.6）

首页按顺序填写：01选择论文文件夹，02选择模板文件夹（总目录或UNEP/WHO等组织子目录）并选择组织与变体，03输入API Key。Key使用密码框，不保存到配置。模型名称及服务地址放在模型设置中；编号文件沿用已保存配置。开始后自动滚动到进度区。

“异常日志”按钮打开文本报告。每个任务保存 `output/exceptions.json`、`output/exceptions.txt`，列明文件/论文、阶段、指定目标、原因和处理建议：文件未读到、PDF解析失败、JSON缺失、未检出指定作者/机构的引用、填表异常、运行异常等。开始前的资源错误保存在 `项目数据/异常日志/`；GUI运行明细另存 `output/运行日志.txt`。

未检出目标引用是程序检测结果，不代表原文确定没有引用，也不会自动排除论文。它由本地程序检查候选数生成，不调用模型。

## 组织工作台与填表质检（0.7）

工作台提供20个常见联合国系统组织下拉选项。选择组织及本地名称变体文件后，自动读取对应目录：

```
模板/
  UNEP/
    引用采集模板.xlsx
    名称变体.json
    名称变体-分组名.json  # 可选，多份时在工作台选择
    字段映射.json        # 标准表头可省略并自动匹配
    报告目录.json        # 可选
  WHO/                  # 待补充 WHO 自己的文件
项目数据/
  界面设置.json          # 不含API Key
  UNEP-编号.json         # 首次明确最后已用编号后创建
解析结果/
  任务-日期时间/
```

组织选项本身不包含名称变体或模板。变体文件必须声明与所选组织完全相同的 `id`；资料不齐时禁用开始按钮，不会回退到其他组织。组织之间分别记住编号文件，也可明确载入共用编号文件。历史UNEP编号档案继续使用，不自动重置。每次任务保存所选资源副本与哈希。

## 引用恢复与内部API检查（0.7.6）

当GROBID把参考文献误归为正文而Docling已正确提取时，程序从Docling的References区恢复目标条目，用原PDF对应区域的文字和坐标核验，记录修复来源。原TEI与原解析JSON保持原样；修复写入最终JSON的引用索引。文末条目不计为正文引用，跨页重复页眉不打断参考文献区。

依照新的流程要求，智谱调用嵌入解析、填表、异常三个环节，界面没有可随意开启的AI质检开关。首页填入Key后，新任务自动加载接口配置；没有Key时本地解析仍可运行，不能称为API验证成功。CLI由api_config明确启用；历史ai_config不恢复旧版语义审查。

每10篇一组，每环节最多一次HTTP请求；每次输入至多24000字符，输出至多1536 tokens，无自动重试。每组最多3次请求。仅发送结构统计、字段映射与程序异常，不审全文、不改引用图、不替代确定性的Excel写入。API状态、回答、接口返回的usage保存在api-stages.json，失败进入exceptions日志，不默认为通过。同任务同输入复用结果，失败或输入改变不自动再次花费；需要重新验证时创建新任务。

管理员仍可显式使用check-api进行一次最小连接诊断。Key只驻留进程，通过环境变量传给后台，不写入配置或日志。

以下为安装和高级命令行使用说明。

## 图形界面（0.5）

安装后可用原生窗口完成操作，不需要在终端填写参数。macOS首次创建应用入口：

```bash
paper-citations install-gui ./论文引用解析.app
```

之后双击应用，选择组织、名称变体和PDF文件夹。侧栏管理模板总目录、模型和编号。运行时显示解析、填表两个进度条，完成后可打开Excel与异常日志。

自定义模板点击“在窗口中配置模板字段”，为每张工作表选择内容类型、表头行、数据起始行，再通过下拉框匹配各列；未知列必须选择字段或明确跳过，映射保存为本地JSON。无须返回终端处理映射。

“继续已有项目”选择run.json，可复用缓存及编号；已有Excel的覆盖会在窗口中确认。停止按钮终止后台解析，已分配编号保留供重试。关闭窗口时，正在运行的任务会先提示。

图形界面使用Tkinter，Python环境需带Tk支持。本机已验证macOS/Python3.12；其他系统可使用 `paper-citations-gui` 或 `python -m paper_citation_pipeline.gui`，尚未做跨平台桌面验证。macOS的.app是指向本机已安装环境的启动器，不内嵌Python或Docling；其他人安装软件包后应在自己电脑上生成入口。GROBID仍需本地服务，Docling模型按原方式安装/下载。

以下保留CLI使用说明供安装、自动化与agent调用。

## 第一次使用：PDF文件夹 + 空白模板

发行包包含可pip安装的wheel、源码包与skill；不需要复制脚本或修改程序。需Python 3.11+（本机已验证3.12）、Docker或可访问的GROBID服务。

解压发行包后，在虚拟环境中安装（尚未发布PyPI，不能省略本地wheel路径）：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install './paper_citation_pipeline-0.8.0-py3-none-any.whl[full]'
```

Windows把激活命令换成 `.venv\Scripts\activate`。使用现有GROBID，或先运行下方Docker命令。首次Docling运行可能下载模型。

```bash
docker run -d --name paper-citations-grobid -p 127.0.0.1:8070:8070 grobid/grobid:0.9.1-crf
paper-citations doctor
paper-citations setup ./my-project --run
```

向导依次取得PDF文件夹、Excel模板、被引目标、可选本地别名文件，以及最后已用的论文号/记录号；已有编号文件通过 `--id-state` 指定。新项目明确填0，续接数据填实际最后编号。需等 `doctor` 显示服务就绪再运行。已有同端口服务则复用，不重复启动容器。

完成后打开 `my-project/output/citations.xlsx`；证据JSON在 `output/json`，阅读稿在 `output/md`，原始TEI也保留。两阶段进度自动显示。机器输出为引用候选及证据，未作语义确认的内容不会冒充已确认。

自动执行或由agent调用可一次传入配置，以下两个0仅适用于全新项目：

```bash
paper-citations setup ./my-project --run --non-interactive \
  --input ./papers --template ./blank.xlsx --target UNEP \
  --aliases ./unep-aliases.json --paper-current 0 --record-current 0
```

标准中文模板自动识别；以citations/papers/reports命名工作表并用程序字段名作表头也可自动识别。其他模板由交互向导逐列配置，或通过 `--mapping ./mapping.json` 提供已确认映射；未知字段不会被猜测或静默丢弃。自动模板识别采用第一行表头；其他位置通过交互或mapping指定。原模板保留，项目中保存副本。

已有项目继续运行：`paper-citations run --config ./my-project/run.json`。新批次修改run.json的input/output并复用编号文件；已有Excel明确覆盖需加 `--overwrite-excel`。可单独运行setup不加 `--run`，先检查配置，再开始转换。

需要让agent调用时额外执行 `paper-citations install-skill`，同名旧skill可用 `--force` 备份更新。普通命令行用户无需安装skill。也可用 `python -m paper_citation_pipeline` 替代命令入口。

## 安装与运行

Python 3.11+。在独立虚拟环境中安装本目录：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install '.[full]'
paper-citations --version
paper-citations init ./my-project
```

Windows 使用 `.venv\Scripts\activate` 激活。基础安装 `pip install .` 可做缓存重封装、JSON验收和模板导出；`[full]` 额外安装 Docling 及其依赖。首次 Docling 运行可能下载模型，需要联网和足够磁盘空间。

GROBID 是独立服务，不随 pip 启动或安装 Docker。已有服务可直接使用；没有服务时可运行：

```bash
docker run --rm -p 8070:8070 grobid/grobid:0.9.1-crf
paper-citations doctor --grobid-url http://localhost:8070
```

全部 GROBID 请求使用原始 PDF，并禁用环境代理继承。不要将隐私论文发送到不受信任的远程 GROBID 地址。

```bash
paper-citations run \
  --input ./input --output ./output --id-state ./numbering.json \
  --target UNEP --aliases ./examples/unep-aliases.json \
  --expect-target --resume
```

目标是**被引用的作者或机构**，不是输入论文的作者筛选条件。未提供别名文件时只使用显式目标名称；不会自动上网猜别名。

如需同时填表：

```bash
paper-citations run --input ./input --output ./output --id-state ./numbering.json \
  --target UNEP --aliases ./examples/unep-aliases.json \
  --template ./blank.xlsx --mapping ./examples/unep-template-map.json \
  --excel ./output/filled.xlsx --expect-target
```

`blank.xlsx` 由使用者放到本地；仓库不携带论文、项目数据或私人模板。示例映射匹配本项目的 v1.2 中文表头，其他模板修改映射即可，不需要修改 Python 代码。

`init` 将随包示例复制到本地并建立空input目录，不依赖Git工作区。也可以使用 `paper-citations run --config my-project/examples/run.json`。配置文件中的相对路径按配置文件所在目录解析；命令行覆盖项按当前工作目录解析。`paper-citations fields` 列出全部模板字段。


## 编号与进度（0.3）

每次 `run` 和 `export` 必须通过 `--id-state ./numbering.json` 或运行配置的 `id_state` 加载本地编号文件。缺失时在转换前停止。初次建档需要明确最后一个已使用的论文号和记录号，不从 PDF 文件名猜测；已有档案直接复用。以下仅为新项目从零开始的示例，续接已有数据须替换两个数值：

```bash
paper-citations init-numbering --output ./numbering.json \
  --paper-current 0 --record-current 0 \
  --paper-prefix UNEP-P --record-prefix UNEP-R --width 6
```

文件包含 `paper.current`、`record.current`（最后已用数字）、各自的 `prefix`、`width`，以及程序维护的 `assigned` 分配表与 `project_id`。当前为100则下一条为101。前缀和宽度在首次运行前确定；运行后不要手动重置计数、改前缀或删分配表。工具拒绝覆盖已有编号文件。同一项目各批次共享并备份该文件，不上传包含数据分配关系的文件到代码仓库。

同一原始 PDF 的 SHA-256 复用论文号；同一目标、同一PDF和同一证据边复用记录号。无目标候选的论文也占一个论文号，记录号不增加；候选边及原文冲突记录各有记录号。编号不表示已确认引用。解析规则变化形成新的证据边会分配新记录号。

编号采用文件锁和原子写入；先持久保存分配，再保存结果。若输出失败可能留有已预留编号，重试复用，不能为了连续而回收。被占用时明确报错，释放锁后重试。该文件应放在本地磁盘；不要复制旧备份与当前文件并行分配。

JSON增加 `numbering.paper_id` 与 `numbering.records`（原证据record_id→展示编号），原 `paper_id`、引用边及原始PDF定位不改。Excel 的 `paper_id`/`record_id` 使用展示编号，因此可从Excel号码查JSON映射回证据。单独导出旧JSON时不改原包，编号对照保存在本地编号文件和XLSX旁的provenance中。

执行时自动输出两阶段文字进度条：PDF→MD/JSON按输入目录PDF总篇数计数，每篇引擎解析、封装和编号完成后前进；模板按本次成功证据包篇数计数，一篇的多条记录统一计为一篇，没有引用记录也计入。第二阶段总数可能小于第一阶段，原因是失败论文不导出。缓存模式明确标为“解析缓存→MD/JSON”。进度中的完成数量是已处理数量，失败另列；模板最后一篇在文件成功保存后才完成。未配置模板则不执行第二阶段。

转换进度另存于输出目录 `conversion-progress.json`；模板进度位于XLSX旁 `*.progress.json`。详细原因和每篇耗时见日志及manifest，不把100%解释成100%引用准确。

## 本地别名文件

```json
{
  "id": "WHO",
  "canonical_name": "World Health Organization",
  "kind": "organization",
  "aliases": ["WHO", "World Health Organization", "World Health Organisation"],
  "domains": ["who.int"],
  "publisher_aliases": ["World Health Organization"]
}
```

也支持简单 JSON 字符串列表。名称按字面匹配，不把内容当正则或代码。配置记录路径、哈希和规则版本进入输出；不修改安装目录里的默认名称表。

个人作者用 `kind: person` 或 `--kind person`，显式给出全名、倒排姓名、缩写及需要识别的姓氏。`examples/person-aliases.json` 为虚构示例。同姓作者、多位同名作者和同年多个条目会保留候选，不能仅凭姓氏确认身份。`publisher_aliases` 与域名只提供机构来源线索，个人作者建议保持为空。

## 自定义 Excel 模板

```json
{
  "sheets": [{
    "sheet": "引用记录",
    "entity": "citations",
    "header_row": 1,
    "start_row": 2,
    "columns": {
      "论文编号*": "paper_id",
      "引用标记原文*": "raw_marker",
      "所在完整段落*": "paragraph_text",
      "目标内容引用确认状态*": "confirmation_status",
      "疑问及缺失原因": "notes"
    }
  }]
}
```

`entity` 支持 `citations`、`papers`、`reports`。完整字段见 [字段说明](docs/fields.md)。按表头精确映射，不猜测字段。模板路径与输出路径必须不同；已有非空目标单元格会被拒绝。默认不覆盖已存在的结果，需要显式 `--overwrite-excel`（run）或 `--overwrite`（export）。普通 `.xlsx` 的样式、工作表、公式、下拉选项和表对象使用 openpyxl 读写；不支持宏模板，含复杂扩展或外部连接的工作簿需另行兼容测试。

```bash
paper-citations export --packets ./output/json --id-state ./numbering.json \
  --template ./blank.xlsx --mapping ./examples/unep-template-map.json \
  --output ./output/filled.xlsx
paper-citations validate ./output/json
```

每行是一个位置到一个候选来源的边。原文编号与题名冲突单列，未确认状态不预填为已确认。无报告清单仍可导出；报告名称状态为待核实。`--catalog-json` 可加载包含 `rows` 的本地清单，每行含 `title,url,date,excel_row`。名称匹配不作为内容引用收录门槛。已有日期或版本差异的匹配在 Excel 中保留原状态说明，降为待核实。

## 输出与范围

```
output/
  tei/*.tei.xml          # 原始 GROBID 响应
  docling/*.docling.json # 原生结构、表格与注释
  json/*.json           # 每篇证据包，主数据
  md/*.md               # 阅读用途
  _parser/              # 两个引擎的原始解析缓存
  manifest.json         # 每篇状态及耗时
  target.json           # 本次目标和本地别名快照
  run_config.json       # 参数与输入资源哈希
  logs/
```

源 PDF 路径及 SHA-256、正文上下文、参考文献、位置和边、PDF文本/坐标、质量问题均保留。目标名称只影响派生索引，不篡改原始解析。GROBID 与 Docling 对每篇并行，论文之间顺序执行。单篇失败记入 manifest；其他成功论文仍可填表，进程返回非零码提醒批次不完整。

已有引擎缓存可用 `--parser-output CACHE` 替代 `--input`，输出必须另建目录。不同目标配置必须使用不同输出目录，防止混入上一目标的结果。

表格允许串行，前提是文本、引用与上下文可回查。JSON保留 Docling 表格单元格、图表说明和原PDF页文本；可确定的图表关联进入 `visual_context`，也写到 notes。图表数字引用有额外原PDF补连。当前并未保证所有图中像素文字、扫描图片、脚注关联或图形数据都被识别；默认不导出图片，对这些内容仍需查原PDF。Markdown从不用于反推引用关系。

退出码：0=处理完成，1=引擎/验收不完整，2=配置或导出错误。`ready_with_issues` 可交给后续 agent，但不是无漏检证明。输出 XLSX 超过单元格字符上限会报错，不静默截断。

## 安装 agent skill

pip 安装的是本地工具，同时携带 skill 文件；不会自动改动用户的 agent 配置。

```bash
paper-citations install-skill
# 已有同名skill时，显式备份并更新
paper-citations install-skill --force
# 也可安装到其他agent支持的skill目录
paper-citations install-skill --path ./skills/paper-citation-pipeline
```

## 上传 GitHub 与分发

将**本目录**作为仓库根目录上传。不要上传父目录中的论文、私人模板、输出或虚拟环境。示例命令中的 OWNER/REPOSITORY 必须换成实际仓库；本项目尚未发布到 GitHub 或 PyPI。

```bash
python -m pip install 'paper-citation-pipeline[full] @ git+https://github.com/OWNER/REPOSITORY.git'
```

发布后可固定 tag 或 commit。构建 wheel/sdist：

```bash
python -m pip install '.[dev]'
python -m build
python -m unittest discover -s tests -v
```

发布前由项目所有者确定开源许可证与归属；当前未擅自授予许可证。GROBID、Docling等依赖的许可由各自项目管理。

打包规范参考 [PyPA pyproject 指南](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/)，Git 安装语法参考 [pip VCS 文档](https://pip.pypa.io/en/stable/topics/vcs-support/)。

参考文献分区对账固定在转换代码中执行。JSON的reference_region_audit记录Docling已识别参考文献区中目标条目的去向：present/recovered/unresolved；未通过原PDF核验的条目进入unresolved和异常日志，不能静默跳过。此检查范围有限，不等于全部参考文献召回率认证。GROBID的funding等区域误分类可能导致漏项，专用参考文献接口仍可能重复同一分区错误；不要盲目重试或把article/light-ref直接设为默认。

0.7.6：识别机构全名[缩写]的作者年份标记；原PDF对账允许横线字形差异但不改原文或数字。带原PDF明确编号的完整Docling条目，可在各片段文字完全覆盖且坐标一致时合并GROBID误拆条目，并同步引用边。报告覆盖年份与出版年份分开保留。PDF定位前缀为数学集合符号∈/∉的区间不计文献引用；[15–17]等真正引用仍按既有规则处理。零候选日志区分目标参考文献未识别与正文索引未连接。


0.7.6内部校验：内置UNEP/EEAP及U.N. Environment变体；用户旧本地变体文件不会被默默覆盖。独立PDF作者年份标记对账，即使已有引用也检查重复次数缺口；未知“已知简称/附属署名”进入日志，不自动承认新身份。此项不覆盖所有数字引用或无标记转述。
上下文在保留原始索引和偏移的前提下，以PDF缩进、连续行距及共享Docling文本块重建；context_audit保留原值与证据。无证据时不重分段；该校验不等于语义或全篇段落边界认证。
AI填表环节在Excel保存和本地回读后执行，输入包含实际文件哈希、逐格比对总数、错误单元格签名及位置，而不是仅有预计行数。api-input-*.json留存模型真实输入，未向模型发送全文。请求仍为每10篇每环节一次，失败不自动重试。自动校验与模型通道成功不得表述为全篇无漏引。

模型返回须通过确定性证据约束：仅采纳输入证据中已存在的论文和异常代码；原始返回与未采纳项分别保留在raw_result、unsupported_findings。参考文献条目数不要求等于正文引用次数。模型仅解释结构检查结果，不独立认证召回率；本地异常不因模型漏报而被清除。


0.7.7运行约定：转换程序自动读取原PDF文字及坐标作证据核验，日常批次不要求agent逐篇人工回看PDF。JSON保留原始索引、引用上下文、修复依据和未解决项；异常未解决不能表述为全篇无漏引。用户明确要求审计或问题无法定位时，才按需检查原文。
每篇完成MD/JSON后立即保存累计Excel快照并回读检查，进度分母为任务总篇数；无需等待整批API检查。中断前已保存的结果可用，编号保持稳定；运行中的表格是部分结果，不代表全批完成。检查点记录在citations.checkpoints.json。为保持模板、报告去重和编号一致，每次从已完成JSON生成累计快照，保存成本随批量增长；并非Excel应用内实时刷新。
批内复用独立Docling进程和模型，GROBID与Docling仍并行；单篇超时/崩溃结束该worker，后续论文重新创建。首篇仍需模型冷启动。不以跳过表格结构、引用检查或无依据截短上下文换取速度。内部AI仍仅作结构检查，不宣称已使用多模态模型审读PDF。


0.7.8新增引用恢复：个人作者署名的目标出版物使用本地完整姓氏与年份、在全部参考文献中唯一匹配，保留推断依据；同名同年不强行连接。数字引用漏进正文索引时，从原PDF标记与参考文献实际印刷编号补回，禁止用列表顺序猜编号。表格文号保留原始代码，不虚构题名/年份；破碎的资源表按PDF列标题、年份行锚点和内嵌官方来源链接恢复整行。仅列管理机构的行留在recall_audit待分类，不当作引用。
共同署名按作者角色纳入，保留原署名，不为UNEP-WCMC建立专属组织同义词白名单。疑似角色由后台API按参考文献证据判断；失败或不确定保留异常。
上下文修复须核验Docling段落与原PDF行位置，防止跨页截断，也不能用局部Docling片段替换更完整的原上下文。原TEI、解析缓存及原始引用偏移始终保留。


0.8.0：通用共同署名规则与疑似作者API判定。每篇最多5次作者判定请求，每次最多512输出token，不自动重试，结果缓存。报告名称未明确匹配仍填数值0。
