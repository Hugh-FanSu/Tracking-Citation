# 模板字段

映射以模板表头为键，字段名为值。缺失字段值留空，未知字段名报错。

## citations

- `record_id`：记录编号*
- `paper_id`：论文编号*
- `report_id`：报告编号（可空）
- `location_id`：引用位置编号*
- `part`：Part统一分类*
- `section_title`：章节标题原文*
- `subsection_title`：小节标题原文
- `pdf_pages`：PDF页序*
- `printed_page`：印刷页码
- `paragraph_id`：段落编号*
- `occurrence_in_paragraph`：段内引用序号*
- `raw_marker`：引用标记原文*
- `citation_sentence`：引用句原文*
- `paragraph_text`：所在完整段落*
- `previous_paragraph`：前一段原文
- `next_paragraph`：后一段原文
- `carrier`：内容载体*
- `raw_reference`：参考文献条目原文*
- `other_references`：同处其他引用原文
- `confirmation_status`：目标内容引用确认状态*
- `context_status`：上下文完整性*
- `notes`：疑问及缺失原因
- `collector`：采集人*
- `reviewer`：复核人
- `processed_date`：处理日期*
- `rule_version`：规则版本*
- `software`：工具与模型版本
- `report_match_status`：具体报告名称匹配状态*
- `report_title`：匹配到的具体报告名称

## papers

- `paper_id`：论文编号*
- `title`：题名原文*
- `doi`：DOI
- `eid`：Scopus EID
- `year`：发表年份*
- `authors`：作者原文
- `journal`：期刊或出版物
- `abstract`：摘要原文*
- `purpose`：研究目的原文（可选）
- `conclusion`：主要结论原文（可选）
- `source_pdf`：PDF文件名或相对路径*
- `file_version`：文件版本*
- `page_count`：PDF总页数
- `fulltext_status`：全文检查状态*
- `batch`：任务包编号*
- `notes`：缺失或其他说明

## reports

- `report_id`：报告编号*
- `target_name`：发布组织*
- `title`：报告题名原文*
- `year`：年份*
- `edition`：版本或系列期次*
- `identifiers`：DOI或ISBN
- `url`：官网链接
- `source_pdf`：PDF文件名或相对路径
- `language`：报告语言
- `verification_status`：核实状态*
- `notes`：备注

其他citation字段：target_marker、source_json、source_pdf、target_name、link_status、visual_context。
其他papers字段：source_json、source_sha256、target_name。

所有confirmation_status均为待核实，reviewer留空。报告名匹配不表示有效引用确认。visual_context是可关联图表的原文标题、脚注、单元格文本JSON。

编号：Excel 的 paper_id、record_id 为本地状态文件分配的展示编号。JSON 原始证据ID仍保留，用 numbering.paper_id 和 numbering.records 回查；不能拿展示编号替换引用图的内部ID。

AI质检结果保存在XLSX旁quality.json/html，不作为引用语义字段写回Excel；0.7移除ai_verdict、ai_reason、ai_report_title、ai_review_status映射字段。
