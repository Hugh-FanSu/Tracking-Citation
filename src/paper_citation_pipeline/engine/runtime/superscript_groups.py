"""Restore printed superscript groups, including ranges wrapped onto the next line."""
import re
import pymupdf
from pipeline import numbers


def recover(pdf,data):
    output=[];by_page={}
    for m in data['citation_mentions']:
        if m.get('style')=='numeric':
            for c in m.get('coordinates',[]):by_page.setdefault(c['page'],[]).append((m,c))
    with pymupdf.open(pdf) as doc:
        for n,page in enumerate(doc,1):
            if n not in by_page:continue
            for block in [dict(lines=[line for b in page.get_text('dict')['blocks'] for line in b.get('lines',[])])]:
                runs=[];active=[];previous_line=None
                for li,line in enumerate(block.get('lines',[])):
                    spans=line['spans'];body=max((s['size'] for s in spans),default=0)
                    for si,s in enumerate(spans):
                        text=s['text'];is_sup=bool(s['flags']&1) or (s['size']<.86*body)
                        numeric=is_sup and re.fullmatch(r'[\d\s,;–—−-]+',text) and text.strip()
                        continuation=active and previous_line!=li and si==0 and re.search(r'[–—−-]\s*$',active[-1][0]) and text.lstrip()[:1].isdigit() and 0<s['bbox'][1]-active[-1][1][1]<30 and s['bbox'][0]<active[-1][1][0]
                        if active and previous_line!=li and not continuation:
                            runs.append(active);active=[]
                        if numeric:
                            active.append((text,list(s['bbox']),li));previous_line=li
                        elif active:runs.append(active);active=[]
                if active:runs.append(active)
                for run in runs:
                    raw=''.join(x[0] for x in run);expanded=numbers(raw)
                    if not expanded or not re.fullmatch(r'\d+(?:\s*[,;–—−-]\s*\d+)*',raw):continue
                    boxes={}
                    for _,box,li in run:boxes[li]=pymupdf.Rect(box) if li not in boxes else boxes[li]|pymupdf.Rect(box)
                    linked={}
                    for m,c in by_page[n]:
                        rect=pymupdf.Rect(c['x'],c['y'],c['x']+c['width'],c['y']+c['height'])
                        if any((rect&box).get_area()>0 for box in boxes.values()) and set(m.get('expanded_numbers',[]))&set(expanded):linked[m['id']]=m
                    if not linked:continue
                    targets=[dict(number=k,target_ids=sorted({t['target_id'] for m in linked.values() for t in m.get('numeric_targets',[]) if t['number']==k and t.get('target_id')})) for k in expanded]
                    output.append(dict(id=f'pdf_sup_group_{len(output)+1}',raw_marker=raw,source='original_pdf_superscript_characters',page=n,bboxes=[list(b) for b in boxes.values()],origin='top-left',unit='PDF point',expanded_numbers=expanded,numeric_targets=targets,citation_ids=list(linked),unresolved_numbers=[t['number'] for t in targets if len(t['target_ids'])!=1],resolution='pdf_verified',context='\n'.join(''.join(s['text'] for s in l['spans']) for li,l in enumerate(block['lines']) if min(x[2] for x in run)<=li<=max(x[2] for x in run))))
    return output
