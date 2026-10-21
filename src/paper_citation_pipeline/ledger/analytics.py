"""Descriptive extraction metrics; no semantic labels are inferred."""
import json
import statistics
from pathlib import Path


def extraction_metrics(result):
    if result.get('excluded'):
        data=json.loads(Path(result['json_location']).read_text())
        return {'status':'excluded' if data.get('exclusion_reason')=='non_english_body_detected' else 'language_pending'}
    from openpyxl import load_workbook
    path=result.get('workbook_location')
    if not path or not Path(path).exists():return {'status':'unavailable'}
    wb=load_workbook(path,read_only=True,data_only=True)
    try:
        if 'citations' not in wb:return {'status':'unavailable'}
        rows=iter(wb['citations'].values);headers=next(rows,None)
        if not headers or 'record_id' not in headers:return {'status':'unavailable'}
        records=set();report_counts={}
        for row in rows:
            d=dict(zip(headers,row))
            if d.get('record_id') is not None and str(d['record_id']) not in records:
                records.add(str(d['record_id']))
                status={'已匹配':'matched','未匹配':'unmatched','待核实':'ambiguous'}.get(d.get('report_match_status'),'not_searched')
                report_counts[status]=report_counts.get(status,0)+1
        return {'status':'parsed','citation_count':len(records),'report_match_counts':report_counts,'basis':'distinct_excel_record_id','schema':1}
    finally:wb.close()


def summarize(tasks):
    # Most recent attempt/version per paper and target. Retries never add another paper.
    seen=set();counts=[];excluded=pending=missing=0;top=[];matches={};matched_papers=reference_matched_papers=0;zero_diagnostics={};review_included=0
    for t in sorted(tasks,key=lambda t:t['updated'],reverse=True):
        identity=(t['paper_id'],t['organization'])
        if identity in seen:continue
        seen.add(identity)
        if t['status']!='completed':continue
        result=json.loads(t['result'] or '{}');m=result.get('extraction_metrics',{})
        status=m.get('status')
        if status=='excluded':excluded+=1
        elif status=='language_pending':pending+=1
        elif status=='parsed':
            n=m['citation_count'];counts.append(n)
            review_included+=int(bool(result.get('pending_review_inclusion',{}).get('included')) and n==0)
            cm=result.get('catalog_match_metrics')
            if cm is None:cm={'not_searched':n}
            for k,v in cm.items():matches[k]=matches.get(k,0)+v
            matched_papers+=int(cm.get('matched',0)>0)
            reference_matched_papers+=int(result.get('catalog_reference_hits',0)>0)
            if n==0:
                reason=result.get('zero_citation_diagnostic','not_audited');zero_diagnostics[reason]=zero_diagnostics.get(reason,0)+1
            top.append({'title':t['title'],'organization':t['organization'],'count':n})
        else:missing+=1
    buckets=[sum(n==0 for n in counts),sum(n==1 for n in counts),sum(2<=n<=3 for n in counts),sum(4<=n<=5 for n in counts),sum(n>=6 for n in counts)]
    return dict(review_included=review_included,included_papers=sum(n>0 for n in counts)+review_included,total_collection_rows=sum(counts)+review_included,report_matches=matches,report_matched_papers=matched_papers,catalog_reference_matched_papers=reference_matched_papers,zero_diagnostics=zero_diagnostics,papers=len(counts),citations=sum(counts),mean=round(statistics.mean(counts),2) if counts else None,median=statistics.median(counts) if counts else None,maximum=max(counts) if counts else None,zero=sum(n==0 for n in counts),excluded=excluded,language_pending=pending,metrics_missing=missing,distribution=list(zip(['1次','2–3次','4–5次','6次及以上'],buckets[1:]))+[('已纳入·次数待复查',review_included)],distribution_total=sum(n>0 for n in counts)+review_included,distribution_unresolved=sum(n==0 for n in counts)-review_included,top=sorted(top,key=lambda x:x['count'],reverse=True)[:5],basis='每篇论文×目标组织的最新任务；引用次数按Excel独立记录号计数；不等于唯一段落数或报告数',review_status='extraction_only')
