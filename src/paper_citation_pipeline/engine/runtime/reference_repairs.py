"""Evidence-backed split of merged hanging-indent bibliography entries.
Only modifies a working copy; original parser JSON remains the evidence of extraction.
"""
import copy
import re
import pymupdf
from standardize_citations import ORG

YEAR=re.compile(r'\b(?:19|20)\d{2}[a-z]?\b')
DATE=re.compile(r'\b(?:19|20)\d{2}[a-z]?\b|n\.\s*d\.',re.I)
ORG_START=re.compile(r'^'+ORG+r'(?:\s*\('+ORG+r'\))?\s*[,.( ]+\s*(?:19|20)\d{2}',re.I)

def repair(pdf,data):
    result=copy.deepcopy(data); corrections=[]
    with pymupdf.open(pdf) as doc:
        page_lines={}
        for b in result['bibliography'][:]:
            raw=b.get('raw_citation') or ''
            if not re.search(r'(?<!\w)'+ORG+r'(?!\w)',raw,re.I):continue
            coords=b.get('coordinates',[])
            if not coords or len({c['page'] for c in coords})!=1:continue
            page=coords[0]['page']
            if page not in page_lines:
                page_lines[page]=[(pymupdf.Rect(l['bbox']),''.join(s['text'] for s in l['spans'])) for block in doc[page-1].get_text('dict')['blocks'] for l in block.get('lines',[])]
            selected=[]
            for c in coords:
                box=pymupdf.Rect(c['x'],c['y'],c['x']+c['width'],c['y']+c['height'])
                hits=[(rect,text,(rect & box).get_area()/max(box.get_area(),.001)) for rect,text in page_lines[page]]
                hit=max(hits,key=lambda x:x[2],default=None)
                if hit and hit[2]>.65 and (hit[0],hit[1]) not in selected:selected.append((hit[0],hit[1]))
            if len(selected)<2:continue
            selected.sort(key=lambda x:x[0].y0)
            margin=min(r.x0 for r,t in selected)
            if max(r.x0 for r,t in selected)-margin>100:continue  # Cross-column starts need separate evidence.
            starts=[i for i,(r,t) in enumerate(selected) if abs(r.x0-margin)<1.6]
            if len(starts)<2 or starts[0]!=0:continue
            if not any(r.x0-margin>4 for r,t in selected) and not all(ORG_START.match(t) for r,t in selected):continue
            segments=[selected[a:b_] for a,b_ in zip(starts,starts[1:]+[len(selected)])]
            texts=[' '.join(t.strip() for r,t in seg) for seg in segments]
            # Every hanging-indent start must introduce a new bibliographic date.
            if not all(DATE.search(t[:240]) for t in texts):continue
            if any(t.lstrip().lower().startswith(('http','doi','accessed','retrieved','available')) for t in texts):continue
            children=[]
            for i,(seg,text) in enumerate(zip(segments,texts)):
                year=DATE.search(text[:240]);label=re.sub(r'\s+','',year.group().lower())
                prefix=text[:year.start()].strip(' .,( ')
                if '(' in text[max(0,year.start()-2):year.start()] and len(prefix.split())>6:
                    title=prefix
                else:
                    title=re.split(r'\.\s+',text[year.end():].lstrip(')., '),maxsplit=1)[0]
                child=copy.deepcopy(b)
                child.update(id=b['id'] if i==0 else b['id']+f'__pdf{i+1}',raw_citation=text,
                             year=label[:4] if label!='n.d.' else None,year_label=label,raw_author_prefix=prefix,title=title,
                             authors=b.get('authors',[]) if i==0 else [],
                             coordinates=[{'page':page,'x':r.x0,'y':r.y0,'width':r.width,'height':r.height,'origin':'top-left','unit':'PDF point'} for r,t in seg],
                             source='original_pdf_hanging_indent_split',numeric_label=None)
                children.append(child)
            pos=result['bibliography'].index(b);result['bibliography'][pos:pos+1]=children
            changes=[]
            for m in result['citation_mentions']:
                if b['id'] not in m.get('target_ids',[]):continue
                years=[re.sub(r'\s+','',x.lower()) for x in DATE.findall(m['raw_marker'])]
                possible=[c for c in children if c['year_label'] in years]
                kept=[x for x in m['target_ids'] if x!=b['id']]
                m['links']=[x for x in m.get('links',[]) if x['target_id']!=b['id']]
                if len(possible)==1:
                    kept.append(possible[0]['id'])
                    m['links'].append({'target_id':possible[0]['id'],'method':'pdf_bibliography_split_unique_citation_year','confidence':None})
                else:m['candidate_target_ids']=list(dict.fromkeys(m.get('candidate_target_ids',[])+[c['id'] for c in children]))
                m['target_ids']=kept
                changes.append({'mention':m['id'],'new_target_ids':kept,'candidate_ids':m.get('candidate_target_ids',[])})
            corrections.append({'kind':'split_merged_reference','old_id':b['id'],'original_raw':raw,
                                'source_sha256':data['source']['sha256'],
                                'children':children,'page':page,'method':'pdf_line_hanging_indent_and_independent_date_starts',
                                'link_changes':changes})
    from docling_bibliography import recover
    corrections.extend(recover(pdf,result))
    # Check the exact PDF location, rather than a context window containing other brackets.
    with pymupdf.open(pdf) as doc:
        for g in result.get('pdf_citation_groups',[])+result.get('recovered_pdf_table_citation_groups',[]):
            if not g.get('bboxes') or not 1<=g.get('page',0)<=len(doc):continue
            x,y,r,b=g['bboxes'][0]
            prefix=doc[g['page']-1].get_text(clip=pymupdf.Rect(x-22,y-.5,x,b+.5)).rstrip()
            if prefix.endswith(('∈','∉')):
                g['citation_validity']='mathematical_set_membership_interval'
                g['validity_evidence']={'prefix':prefix,'source':'original_pdf_at_marker_coordinates'}
    return result,corrections
