"""Human-readable operational exceptions; never claims zero hits prove absence."""
from datetime import datetime
import os
from pathlib import Path
from .config import read_json
from .numbering import atomic_json


def save_exceptions(path,issues,target=None,secrets=()):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    keys=[s for s in (*secrets,os.environ.get('PAPER_CITATIONS_API_KEY','')) if isinstance(s,str) and s]
    def clean(value):
        if isinstance(value,str):
            for key in keys:value=value.replace(key,'[redacted]')
        elif isinstance(value,list):value=[clean(v) for v in value]
        elif isinstance(value,dict):value={k:clean(v) for k,v in value.items()}
        return value
    data=clean({'created_at':datetime.now().isoformat(timespec='seconds'),'target':target,'count':len(issues),'issues':issues})
    atomic_json(path,data)
    lines=['论文引用处理异常日志',f'时间：{data["created_at"]}',f'指定作者/机构：{data["target"] or "未指定"}',f'异常/待检查项：{data["count"]}',
           '“未检出目标引用”是程序检测结果，不代表原文确定不存在引用。','']
    for i,item in enumerate(data['issues'],1):
        lines.extend([f'{i}. [{item.get("severity","warning")}] {item["kind"]}',
                      '文件/论文：'+str(item.get('file') or item.get('paper') or '整个任务'),
                      '阶段：'+str(item.get('stage','')),'原因：'+str(item.get('reason','')),
                      '处理建议：'+str(item.get('action','查看运行日志后重试。')),''])
    if not issues:lines.append('本次未发现运行异常或未检出目标引用的论文。此结果不表示引用语义已核实。')
    path.with_suffix('.txt').write_text('\n'.join(lines),encoding='utf-8')
    return path


def collect_exceptions(output,target=None,input_dir=None,extra=(),workbook=None):
    output=Path(output);issues=list(extra)
    manifest_path=output/'manifest.json'
    try:manifest=read_json(manifest_path) if manifest_path.exists() else []
    except (OSError,ValueError) as exc:
        manifest=[];issues.append(dict(kind='运行清单无法读取',stage='解析',file=str(manifest_path),reason=str(exc),severity='error'))
    source_files={}
    if input_dir and Path(input_dir).is_dir():
        try:source_files={p.stem:str(p) for p in Path(input_dir).iterdir() if p.suffix.lower()=='.pdf' and p.is_file()}
        except OSError as exc:issues.append(dict(kind='论文目录无法读取',stage='输入',file=str(input_dir),reason=str(exc),severity='error'))
    seen=set()
    for row in manifest:
        paper=row['paper'];seen.add(paper);file=source_files.get(paper,paper+'.pdf')
        if row.get('readiness')=='failed':
            issues.append(dict(kind='论文处理失败',stage='解析',paper=paper,file=file,severity='error',reason='；'.join(map(str,row.get('validation_errors',[]))) or '未能生成可用结构化结果',action='检查PDF是否可读取、GROBID/Docling状态及该论文运行日志。'))
            continue
        if row.get('readiness')=='excluded':
            uncertain=row.get('exclusion_reason')=='language_undetermined'
            issues.append(dict(kind='语种待确认，未纳入' if uncertain else '非英语论文已排除',stage='语种筛选',
                paper=paper,file=file,severity='warning' if uncertain else 'info',
                reason=str(row.get('language',{})),action='检查文字层或OCR后重试。' if uncertain else '按仅英语规则排除，无需处理引用。'))
            continue
        count=row.get('target_candidates')
        packet=output/'json'/(paper+'.json')
        if not packet.is_file():
            issues.append(dict(kind='解析JSON未读到',stage='输出',paper=paper,file=str(packet),severity='error',reason='运行清单显示成功，但对应JSON文件不存在。'));continue
        try:
            packet_data=read_json(packet)
            if count is None:count=len(packet_data['target_candidates'])
            for blocker in packet_data.get('local_verification',{}).get('blockers',[]):
                issues.append(dict(kind='本地证据核验未通过，暂不可交付',stage='删除PDF前检查',paper=paper,file=str(packet),severity='warning',reason=str(blocker),action='保留PDF；查看local_verification和semantic-review中的证据与失败原因。'))
            for finding in packet_data.get('recall_audit',{}).get('findings',[]):
                issues.append(dict(kind='引用覆盖检查未通过',stage='目标匹配',paper=paper,file=str(packet),severity='warning',reason=str(finding),action='检查标记与名称变体；已有一次命中不代表重复引用均已关联。'))
            audit=packet_data.get('reference_region_audit',{})
            if audit.get('status') in {'repaired','needs_attention'}:
                pending=sum(e['status']=='unresolved' for e in audit['entries'])
                recovered=sum(e['status']=='recovered' for e in audit['entries'])
                issues.append(dict(kind='参考文献分区对账',stage='解析',paper=paper,file=str(packet),severity='warning' if pending else 'info',reason=f'已恢复{recovered}条；仍有{pending}条未通过核验。',action='查看JSON的reference_region_audit与corrections；未核验条目不会强行建立引用关系。'))
        except (ValueError,OSError,KeyError,TypeError) as exc:
            issues.append(dict(kind='解析JSON无法读取',stage='输出',paper=paper,file=str(packet),severity='error',reason=str(exc)));continue
        if count==0:
            references=packet_data.get('citation_index',{}).get('references',[])
            target_refs=[r for r in references if r.get('organization_candidate')]
            unlinked=packet_data.get('unresolved',{}).get('unlinked_organization_year',[])
            detail=(f'已识别目标参考文献{len(target_refs)}条，但未建立正文到这些条目的引用关系；需检查正文标记和目标索引。' if target_refs else '参考文献索引未识别到目标条目；需检查名称变体、条目拆分及分区。')
            detail+=f' 未链接作者年份标记{len(unlinked)}处；分区对账状态：{audit.get("status","未执行")}。'
            issues.append(dict(kind='未检出指定作者或机构的引用',stage='目标匹配',paper=paper,file=file,severity='warning',reason=f'目标 {target or "所选目标"} 的引用候选为0；PDF名称命中数：{row.get("pdf_target_mentions","未知")}。'+detail,action='查看JSON中citation_index、reference_region_audit及unresolved定位断点；此项不等于原文没有引用，不自动排除论文。'))
    for paper in sorted(set(source_files)-seen):
        issues.append(dict(kind='论文未完成读取',stage='解析',paper=paper,file=source_files[paper],severity='error',reason='输入目录存在该PDF，但运行清单没有对应处理结果。',action='查看运行错误或中断原因，继续项目重试。'))
    quality=Path(workbook or output/'citations.xlsx').with_suffix('.quality.json')
    if quality.exists():
        try:
            report=read_json(quality)
            if report.get('status')=='failed':issues.append(dict(kind='结果检查失败',stage='质检',file=str(quality),severity='error',reason=report.get('error','未知错误'),action='查看运行日志；Excel已保留。'))
            merged={c['id']:dict(c) for c in report.get('checks',[])}
            for ai in report.get('ai_checks',[]):
                current=merged.setdefault(ai['id'],dict(ai))
                if ai['status'] in {'warning','error'}:
                    if current.get('status')=='pass':current.update(status=ai['status'],reason=ai.get('reason'))
                    elif ai['status']=='error':current['status']='error'
            for check in merged.values():
                if check.get('status') in {'warning','error'}:
                    issues.append(dict(kind='填表结果异常',stage='质检',file=str(quality.with_suffix('.html')),paper=check.get('paper_id'),severity=check['status'],reason=check.get('reason') or f'{check.get("kind")}；工作表={check.get("sheet","")}；行={check.get("row","")}；字段={check.get("field","")}',action='打开质检报告查看具体位置及缺失原因。'))
        except (ValueError,OSError,KeyError) as exc:issues.append(dict(kind='质检报告无法读取',stage='质检',file=str(quality),severity='error',reason=str(exc)))
    api_path=output/'api-stages.json'
    if api_path.exists():
        for call in read_json(api_path).get('calls',[]):
            if call['status']!='completed':issues.append(dict(kind='API环节未完成',stage=call['stage'],file=str(api_path),severity='error',reason=call.get('error','请求中断或状态未知；未自动重试')))
            else:
                for finding in call.get('result',{}).get('findings',[]):issues.append(dict(kind='API运行检查提示',stage=call['stage'],paper=finding['paper'],file=str(api_path),severity='warning',reason=finding['message']))
    return save_exceptions(output/'exceptions.json',issues,target)
