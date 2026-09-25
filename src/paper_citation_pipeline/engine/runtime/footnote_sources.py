"""Recover source-bearing numbered footnotes, keeping invalid supra pointers explicit."""
import re
from collections import Counter
import pymupdf
from standardize_citations import ORG, org_reference, uid
from target_recovery import coord, add_edge, compact

TARGET_START=re.compile(r'^\s*'+ORG+r'(?!\w)',re.I)
SUPRA=re.compile(r'\bsupra\s+note\s+(\d+)\b',re.I)


def coordinate_rect(c):
    if 'bbox' in c:return pymupdf.Rect(c['bbox'])
    if {'x','y','width','height'}<=c.keys():return pymupdf.Rect(c['x'],c['y'],c['x']+c['width'],c['y']+c['height'])
    return pymupdf.Rect()


def read_notes(page):
    lines=[l for b in page.get_text('dict')['blocks'] for l in b.get('lines',[]) if abs(l.get('dir',(1,0))[1])<.05]
    sizes=Counter()
    for l in lines:
        for s in l['spans']:
            if s['bbox'][1]<page.rect.height*.7:sizes[round(s['size'],1)]+=len(s['text'])
    if not sizes:return []
    main=sizes.most_common(1)[0][0];starts=[]
    for i,l in enumerate(lines):
        spans=[s for s in l['spans'] if s['text'].strip()]
        if len(spans)<2 or l['bbox'][1]<page.rect.height*.5:continue
        if not re.fullmatch(r'\d{1,3}',spans[0]['text'].strip()):continue
        body=max(s['size'] for s in spans[1:])
        if not (spans[0]['size']<body*.8 and body<main*.9):continue
        starts.append((i,int(spans[0]['text']),spans[0]['bbox'][0],body))
    # Distinguish a run of footnotes from an isolated chart/axis label.
    if len(starts)<2:return []
    notes=[]
    for j,(i,n,left,size) in enumerate(starts):
        stop=starts[j+1][0] if j+1<len(starts) else len(lines)
        chosen=[lines[i]]
        for l in lines[i+1:stop]:
            if l['bbox'][0]<left-2 or l['bbox'][0]>left+30:break
            if l['bbox'][1]-chosen[-1]['bbox'][3]>size*2:break
            if any(s['size']>size*1.2 for s in l['spans']):break
            chosen.append(l)
        text=' '.join(''.join(s['text'] for s in l['spans']).strip() for l in chosen)
        text=re.sub(r'^\s*'+str(n)+r'\s*','',text,count=1)
        notes.append(dict(number=n,text=text,lines=chosen,top=lines[i]['bbox'][1]))
    return notes


def recover(pdf,index):
    changes=[];findings=[]
    with pymupdf.open(pdf) as doc:
        pages=[read_notes(p) for p in doc];by_number={}
        for ns in pages:
            for note in ns:by_number.setdefault(note['number'],[]).append(note)
        for page_no,(page,notes) in enumerate(zip(doc,pages),1):
            for note in notes:
                parts=[p.strip() for p in note['text'].split(';') if TARGET_START.match(p)]
                if not parts:continue
                for raw in parts:
                    supra=SUPRA.search(raw);resolved=raw;title=None;year=None
                    pointer_status=None
                    if supra:
                        destinations=by_number.get(int(supra[1]),[])
                        target_parts=[p.strip() for dest in destinations for p in dest['text'].split(';') if TARGET_START.match(p) and not SUPRA.search(p)]
                        if len(destinations)==1 and len(target_parts)==1:
                            resolved=target_parts[0];pointer_status='resolved_explicit_number'
                        else:
                            pointer_status='unresolved_or_conflicting_number'
                            findings.append(dict(code='footnote_cross_reference_conflict',page=page_no,note_number=note['number'],raw_note=note['text'],cited_note_number=int(supra[1]),destination_notes=[d['text'] for d in destinations],reason='Named target is explicit; report identity cannot be inferred by silently changing the footnote number'))
                    if not supra or pointer_status=='resolved_explicit_number':
                        m=re.search(r'\(\s*((?:19|20)\d{2})\s*\)',resolved)
                        if m:year=m[1]
                        title=re.sub(r'^'+ORG+r'\s*(?:\('+ORG+r'\))?\s*[,.:]\s*','',resolved,flags=re.I)
                        title=re.sub(r'\s*\((?:19|20)\d{2}\)\.?\s*$','',title)
                    identity=org_reference(dict(raw_citation=resolved,authors=[],year=year))
                    if not identity:continue
                    # The source is evidenced by this note, not a global bibliography ordinal.
                    ident=uid('footnote_ref',index['document_id'],page_no,note['number'],raw)
                    r=dict(id=ident,reference_id=uid('ref',ident),raw_citation=resolved,title=title,year=year,authors=[],coordinates=[coord(page_no,l['bbox']) for l in note['lines']],source='original_pdf_numbered_footnote',organization_candidate=identity,attribution_evidence=dict(raw_note=note['text'],note_number=note['number'],pointer_status=pointer_status))
                    for block in page.get_text('dict')['blocks']:
                        if block['bbox'][1]>=min(n['top'] for n in notes):continue
                        lines=block.get('lines',[]);text='\n'.join(''.join(s['text'] for s in l['spans']) for l in lines)
                        hits=[s for l in lines for s in l['spans'] if s['text'].strip()==str(note['number']) and s['flags']&1]
                        for hit in hits:
                            rect=pymupdf.Rect(hit['bbox'])
                            existing=[o for o in index['occurrences'] if any(c.get('page')==page_no and (coordinate_rect(c)&rect).get_area()>rect.get_area()*.8 for c in o.get('coordinates',[])) and o['raw_marker'].strip()==str(note['number'])]
                            if any(any(e['reference_id'] in {rr['reference_id'] for rr in index['references'] if rr.get('organization_candidate') and compact(rr['raw_citation'])==compact(resolved)} for e in o['links']) for o in existing):continue
                            if not any(rr['id']==ident for rr in index['references']):index['references'].append(r)
                            pid=uid('note_context',index['document_id'],page_no,list(block['bbox']))
                            if not any(p['id']==pid for p in index['contexts']):index['contexts'].append(dict(id=pid,text=text,kind='p',section_id=None,coordinates=[coord(page_no,block['bbox'])],sentences=[],previous_paragraph_id=None,next_paragraph_id=None))
                            location=uid('note_location',index['document_id'],page_no,list(hit['bbox']))
                            o=next((o for o in index['occurrences'] if o['location_id']==location),None)
                            if o is None:
                                o=dict(location_id=location,raw_marker=str(note['number']),marker_source='original_pdf_footnote_callout',citation_form='footnote_source',paragraph_id=pid,offsets=dict(start=None,end=None,unit='unicode_codepoint',end_exclusive=True),coordinates=[coord(page_no,hit['bbox'])],source_evidence_ids=[ident],links=[],human_review_status='not_reviewed',style='numeric',typography='superscript',carrier='p',expanded_numbers=[],unresolved_numbers=[])
                                index['occurrences'].append(o)
                            if add_edge(index,o,r,'original_pdf_body_callout_to_same_page_numbered_footnote'):
                                changes.append(dict(kind='recover_footnote_source',location_id=location,reference_id=r['reference_id'],evidence=r['attribution_evidence']))
    return changes,findings
