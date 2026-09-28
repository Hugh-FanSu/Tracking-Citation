# 本地配置

别名JSON可以是字符串列表，也可以是对象：

```json
{"id":"WHO","canonical_name":"World Health Organization","kind":"organization","aliases":["WHO","World Health Organization","World Health Organisation"],"domains":["who.int"],"publisher_aliases":["World Health Organization"]}
```

个人作者用 `kind: person`，明确列出全名、倒排姓名、缩写及必要的姓氏；不能把这个清单当作同姓消歧保证。名称为字面量，不是正则。UNEP专用兼容规则只在UNEP profile中启用，不扩散到其他目标。

模板映射示例：

```json
{"sheets":[{"sheet":"引用记录","entity":"citations","header_row":1,"start_row":2,"columns":{"论文编号*":"paper_id","引用标记原文*":"raw_marker","所在完整段落*":"paragraph_text","前一段原文":"previous_paragraph","后一段原文":"next_paragraph","疑问及缺失原因":"notes"}}]}
```

实体支持 citations、papers、reports，映射左侧是模板原表头，右侧是程序字段。notes包含来源JSON、局部来源ID、歧义和图表上下文；模板有专栏时可额外映射 visual_context。只改mapping，不能臆造未知模板字段。详细字段清单随工具项目的 docs/fields.md 提供，程序也会在未知字段时明确报错。

运行JSON支持 input 或 parser_output（二选一）、output、target、aliases、kind、template、mapping、excel、catalog_json、grobid_url、ocr、resume、expect_target、必需的 id_state，以及可选 api_config（书目、原文上下文和覆盖证据核验）。相对路径以配置文件目录为基准，CLI覆盖路径以当前目录为基准。

无catalog_json时报告名称待核实；有本地清单时每条须含 title、url、date、excel_row。清单日期不必然等于出版年。名称匹配不会替代内容引用确认。

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

填表后程序质检进度为XLSX旁 `*.quality-progress.json`。本地结构检查自动执行；api_config启用限额证据语义核验；upload-readiness.json单列当前交付状态，旧ai_config忽略。详情见SKILL.md。
