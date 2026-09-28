"""Recover source-bearing numbered footnotes, keeping invalid supra pointers explicit."""
import re
from collections import Counter
import pymupdf
from pdf_evidence import open_document
from standardize_citations import ORG, org_reference, uid
from target_recovery import coord, add_edge, compact

TARGET_START=re.compile(r'^\s*'+ORG+r'(?!\w)',re.I)
SUPRA=re.compile(r'\b(?:supra\s+note|above\s+n(?:ote)?\.?)\s+(\d+)\b',re.I)
SHORT=re.compile(r'^\s*(?:ibid\.?\s*(?:at\s+[^.;]+)?|at\s+(?:\[?\d+\]?(?:[–−-]\d+)?))\s*(?:[.;]|$)',re.I)
SOURCE_CUE=re.compile(r'\bsee(?:\s+generally|\s+also)?\s+('+ORG+r')(?!\w)',re.I)


def coordinate_rect(c):
    if 'bbox' in c:return pymupdf.Rect(c['bbox'])
    if {'x','y','width','height'}<=c.keys():return pymupdf.Rect(c['x'],c['y'],c['x']+c['width'],c['y']+c['height'])
    return pymupdf.Rect()


def read_notes(page):
    original=[l for b in page.get_text('dict')['blocks'] for l in b.get('lines',[]) if abs(l.get('dir',(1,0))[1])<.05]
    # Some legal publishers place the number in a separate line object on the
    # same baseline. Join only nearby, non-overlapping horizontal fragments.
    lines=[]
    for line in sorted(original,key=lambda l:(round(l['bbox'][1],1),l['bbox'][0])):
        previous=next((l for l in reversed(lines[-4:]) if abs(l['bbox'][3]-line['bbox'][3])<2 and 0<=line['bbox'][0]-l['bbox'][2]<35),None)
        if previous is not None:
            previous['spans']+=line['spans'];previous['bbox']=tuple(pymupdf.Rect(previous['bbox'])|pymupdf.Rect(line['bbox']))
        else:lines.append(dict(line,spans=list(line['spans'])))
    sizes=Counter()
    for l in lines:
        for span in l['spans']:
            if span['bbox'][1]<page.rect.height*.45:sizes[round(span['size'],1)]+=len(span['text'])
    if not sizes:return []
    main=sizes.most_common(1)[0][0];starts=[]
    for i,l in enumerate(lines):
        spans=[v for v in l['spans'] if v['text'].strip()]
        if not spans or l['bbox'][1]<page.rect.height*.4:continue
        first=spans[0]['text']
        standalone=re.fullmatch(r'\d{1,3}',first.strip())
        inline=re.match(r'^(\d{1,3})\s{2,}\S',first)
        if standalone and len(spans)>1:
            number=int(first.strip());body=max(v['size'] for v in spans[1:])
        elif inline:
            number=int(inline[1]);body=max(v['size'] for v in spans)
        else:continue
        if not (spans[0]['size']<=body*1.05 and body<main*.9):continue
        starts.append((i,number,spans[0]['bbox'][0],body))
    # Repeated aligned note starts are required; an isolated numeric label is
    # insufficient, even when its font is small.
    starts=[a for a in starts if any(a!=b and abs(a[2]-b[2])<3 for b in starts)]
    if len(starts)<2:return []
    notes=[]
    for j,(i,n,left,size) in enumerate(starts):
        stop=starts[j+1][0] if j+1<len(starts) else len(lines)
        chosen=[lines[i]]
        for l in lines[i+1:stop]:
            if l['bbox'][0]<left-2 or l['bbox'][0]>left+30:break
            if l['bbox'][1]-chosen[-1]['bbox'][3]>size*2:break
            if any(v['size']>size*1.2 for v in l['spans']):break
            chosen.append(l)
        text=' '.join(''.join(v['text'] for v in l['spans']).strip() for l in chosen)
        text=re.sub(r'^\s*'+str(n)+r'\s*','',text,count=1)
        notes.append(dict(number=n,text=text,lines=chosen,top=lines[i]['bbox'][1]))
    return notes


def target_parts(text):
    parts=[]
    for part in text.split(';'):
        part=part.strip()
        if TARGET_START.match(part):parts.append(part)
        else:
            cue=SOURCE_CUE.search(part)
            if cue:parts.append(part[cue.start(1):])
    return parts


def resolved_note(note,by_number,seen=()):
    key=(note['page'],note['number'])
    if key in seen:return None
    parts=target_parts(note['text'])
    if len(parts)==1:
        pointer=SUPRA.search(parts[0])
        if not pointer:return parts[0]
        dest=by_number.get(int(pointer[1]),[])
        if len(dest)==1 and dest[0]['number']<note['number']:
            return resolved_note(dest[0],by_number,seen+(key,))
    # A bare pinpoint or ibid refers only to the immediately preceding,
    # uniquely identified note on the same page. Mixed sources are excluded.
    if SHORT.match(note['text']):
        prev=by_number.get(note['number']-1,[])
        if len(prev)==1 and prev[0]['page']==note['page']:
            text=prev[0]['text']
            prior_short=SHORT.match(text)
            single_short=not prior_short or not text[prior_short.end():].strip()
            if single_short and ';' not in text and not re.search(r'\b(?:and|also)\s+(?:see|cf)\b',text,re.I):
                return resolved_note(prev[0],by_number,seen+(key,))
    return None


def note_context(doc,pages,index,page_no,block,hit):
    def body_blocks(n):
        pg=doc[n-1];notes=pages[n-1]
        limit=min((v['top'] for v in notes),default=pg.rect.height*.9)
        note_size=max((v['size'] for n in notes for l in n['lines'] for v in l['spans']),default=0)
        return [b for b in pg.get_text('dict')['blocks'] if b.get('lines') and b['bbox'][1]>pg.rect.height*.08 and b['bbox'][3]<limit and max((v['size'] for l in b['lines'] for v in l['spans'] if len(v['text'].strip())>5),default=0)>note_size*1.05 and len(''.join(v['text'] for l in b['lines'] for v in l['spans']).strip())>40]
    def text(b):return '\n'.join(''.join(v['text'] for v in l['spans']) for l in b['lines'])
    def continued(left,right):
        lt=text(left).rstrip();rt=text(right).lstrip()
        ls=[v['size'] for l in left['lines'] for v in l['spans'] if len(v['text'].strip())>5]
        rs=[v['size'] for l in right['lines'] for v in l['spans'] if len(v['text'].strip())>5]
        return bool(lt and rt and rt[0].islower() and re.search(r'[A-Za-z,]$',lt) and ls and rs and abs(max(ls)-max(rs))<.5)
    pieces=[(page_no,block)]
    here=body_blocks(page_no)
    if here and tuple(block['bbox'])==tuple(here[-1]['bbox']) and page_no<len(doc):
        nxt=body_blocks(page_no+1)
        if nxt and continued(block,nxt[0]):pieces.append((page_no+1,nxt[0]))
    if here and tuple(block['bbox'])==tuple(here[0]['bbox']) and page_no>1:
        prev=body_blocks(page_no-1)
        if prev and continued(prev[-1],block):pieces.insert(0,(page_no-1,prev[-1]))
    chunks=[];offset=None;length=0
    for pn,b in pieces:
        for line in b['lines']:
            for span in line['spans']:
                if pn==page_no and tuple(span['bbox'])==tuple(hit['bbox']):offset=length+len(span['text'])-len(span['text'].lstrip())
                chunks.append(span['text']);length+=len(span['text'])
            chunks.append('\n');length+=1
    content=''.join(chunks);coords=[coord(n,b['bbox']) for n,b in pieces]
    headings=[]
    for sec in index.get('sections',[]):
        for cr in sec.get('coordinates',[]):
            if (cr['page'],cr['y'])<(coords[0]['page'],coords[0]['y']):headings.append(((cr['page'],cr['y']),sec['id']))
    section=max(headings,default=(None,None),key=lambda x:x[0])[1]
    sentences=[];start=0
    for match in re.finditer(r'[.!?](?:["”])?(?:\d+(?:,\d+)*)?(?=\s+[A-Z]|\s*$)',content):
        end=match.end();sentences.append(dict(text=content[start:end].strip(),start=start,end=end,source='original_pdf_sentence_boundary_heuristic'));start=end
    pid=uid('note_context',index['document_id'],coords)
    if not any(v['id']==pid for v in index['contexts']):
        index['contexts'].append(dict(id=pid,text=content,kind='p',section_id=section,coordinates=coords,sentences=sentences,previous_paragraph_id=None,next_paragraph_id=None,source='original_pdf_body_block',continuation_evidence='adjacent_page_lowercase_continuation_and_matching_body_font' if len(pieces)>1 else None))
    return pid,offset


def recover(pdf,index):
    changes=[];findings=[]
    with open_document(pdf) as doc:
        pages=[read_notes(p) for p in doc];by_number={}
        for page_no,ns in enumerate(pages,1):
            for note in ns:
                note['page']=page_no
                by_number.setdefault(note['number'],[]).append(note)
        for page_no,(page,notes) in enumerate(zip(doc,pages),1):
            for note in notes:
                parts=target_parts(note['text'])
                inherited=resolved_note(note,by_number) if SHORT.match(note['text']) else None
                if not parts and inherited:parts=[inherited]
                if not parts:continue
                for raw in parts:
                    supra=SUPRA.search(raw);resolved=raw;title=None;year=None
                    pointer_status='resolved_same_page_previous_note' if inherited else None
                    if supra:
                        destinations=by_number.get(int(supra[1]),[])
                        destination=resolved_note(note,by_number)
                        if len(destinations)==1 and destination:
                            resolved=destination;pointer_status='resolved_explicit_number'
                        else:
                            pointer_status='unresolved_or_conflicting_number'
                            findings.append(dict(code='footnote_cross_reference_conflict',page=page_no,note_number=note['number'],raw_note=note['text'],cited_note_number=int(supra[1]),destination_notes=[d['text'] for d in destinations],reason='Named target is explicit; report identity cannot be inferred by silently changing the footnote number'))
                    if not supra or pointer_status=='resolved_explicit_number':
                        m=re.search(r'\([^()]*?\b((?:19|20)\d{2})\s*\)',resolved)
                        if m:year=m[1]
                        title=re.sub(r'^'+ORG+r'\s*(?:\('+ORG+r'\))?\s*[,.:]?\s*','',resolved,flags=re.I)
                        title=re.sub(r'\s*\([^()]*?(?:19|20)\d{2}\).*$', '',title).strip()
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
                            pid,offset=note_context(doc,pages,index,page_no,block,hit)
                            location=uid('note_location',index['document_id'],page_no,list(hit['bbox']))
                            o=next((o for o in index['occurrences'] if o['location_id']==location),None)
                            if o is None:
                                o=dict(location_id=location,raw_marker=str(note['number']),marker_source='original_pdf_footnote_callout',citation_form='footnote_source',paragraph_id=pid,offsets=dict(start=offset,end=offset+len(str(note['number'])) if offset is not None else None,unit='unicode_codepoint',end_exclusive=True),coordinates=[coord(page_no,hit['bbox'])],source_evidence_ids=[ident],links=[],human_review_status='not_reviewed',style='numeric',typography='superscript',carrier='p',expanded_numbers=[],unresolved_numbers=[])
                                index['occurrences'].append(o)
                            if add_edge(index,o,r,'original_pdf_body_callout_to_same_page_numbered_footnote'):
                                changes.append(dict(kind='recover_footnote_source',location_id=location,reference_id=r['reference_id'],evidence=r['attribution_evidence']))
    return changes,findings
