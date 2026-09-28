"""Restore IEEE [a]–[b] ranges using PDF characters and an existing citation anchor."""
import re
import pymupdf
from pdf_evidence import open_document


def recover(pdf,data):
    additions=[]
    with open_document(pdf) as doc:
        for page_no,page in enumerate(doc,1):
            for block in page.get_text('rawdict')['blocks']:
                chars=[]
                for li,line in enumerate(block.get('lines',[])):
                    chars.extend((c['c'],c['bbox'],li) for s in line['spans'] for c in s['chars'])
                    chars.append(('\n',None,li))
                text=''.join(c[0] for c in chars)
                for m in re.finditer(r'\[(\d{1,3})\]\s*[–—−-]\s*\[(\d{1,3})\]',text):
                    lo,hi=map(int,m.groups())
                    if not 0<lo<hi or hi-lo>100:continue
                    boxes={}
                    for _,box,li in chars[m.start():m.end()]:
                        if box is not None:boxes[li]=pymupdf.Rect(box) if li not in boxes else boxes[li]|pymupdf.Rect(box)
                    if len(boxes)>2:continue
                    bb=list(boxes.values())
                    if len(bb)==2 and not 0<bb[1].y0-bb[0].y0<30:continue
                    linked=[]
                    for mention in data['citation_mentions']:
                        if mention.get('style')!='numeric' or not set(mention.get('expanded_numbers',[]))&{lo,hi}:continue
                        for c in mention.get('coordinates',[]):
                            r=pymupdf.Rect(c['x'],c['y'],c['x']+c['width'],c['y']+c['height'])
                            if c['page']==page_no and any((r&box).get_area()>0 for box in boxes.values()):linked.append(mention);break
                    if not linked:continue
                    ids={x['id'] for x in linked}
                    if any(g.get('citation_validity')=='mathematical_set_membership_interval' and ids.intersection(g.get('citation_ids',[])) for g in data.get('pdf_citation_groups',[])):continue
                    targets=[dict(number=n,target_ids=sorted({t['target_id'] for x in linked for t in x.get('numeric_targets',[]) if t['number']==n and t.get('target_id')})) for n in range(lo,hi+1)]
                    additions.append(dict(id=f'pdf_bracket_range_{len(additions)+1}',raw_marker=m.group(),source='original_pdf_bracket_range_characters',page=page_no,bboxes=[list(b) for b in boxes.values()],origin='top-left',unit='PDF point',expanded_numbers=list(range(lo,hi+1)),numeric_targets=targets,citation_ids=[x['id'] for x in linked],unresolved_numbers=[t['number'] for t in targets if len(t['target_ids'])!=1],resolution='pdf_verified',context=text))
    replaced={cid for g in additions for cid in g['citation_ids']}
    data['pdf_citation_groups']=[g for g in data.get('pdf_citation_groups',[]) if not replaced.intersection(g['citation_ids'])]+additions
    return [dict(kind='restore_bracket_endpoint_range',raw_marker=g['raw_marker'],page=g['page'],expanded_numbers=g['expanded_numbers']) for g in additions]
