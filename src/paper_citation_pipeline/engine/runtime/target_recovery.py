"""Recover citation edges from independent PDF evidence, without editing raw parser output."""
import re
import unicodedata
import pymupdf
from standardize_citations import uid,org_reference,ORG,ALIASES


def compact(text):
    return ''.join(c for c in unicodedata.normalize('NFKD',text).casefold() if c.isalnum())


def coord(page,box):
    x,y,r,b=box
    return dict(page=page,x=x,y=y,width=r-x,height=b-y,origin='top-left',unit='PDF point')


def add_edge(index, occurrence, reference, method):
    if any(l['reference_id']==reference['reference_id'] for l in occurrence['links']):return False
    occurrence['links'].append(dict(edge_id=uid('edge',occurrence['location_id'],reference['reference_id']),
        local_reference_id=reference['id'],reference_id=reference['reference_id'],methods=[method],
        link_status='inferred_unique_local_reference',target_marker=occurrence['raw_marker']))
    return True


def recover_joint_authors(index):
    from standardize_citations import alias_pattern,envelope
    changes=[]
    refs=index['references']
    for r in refs:
        identity=r.get('organization_candidate') or {};joint=identity.get('joint_authorship');year=identity.get('year_label_from_raw')
        if not joint or not year or identity.get('mixed_reference'):continue
        parts=joint['coauthors']
        signature=lambda x:tuple(sorted(compact(v) for v in x.get('coauthors',[])))
        peers=[b for b in refs if (b.get('organization_candidate') or {}).get('year_label_from_raw')==year and signature((b.get('organization_candidate') or {}).get('joint_authorship') or {})==signature(joint)]
        if len(peers)!=1:continue
        label=r'\s*(?:&|and|,|/|-)\s*'.join(alias_pattern(x.strip(' .')) for x in parts)
        pattern=re.compile(r'(?<!\w)'+label+r'\s*[,.(]\s*'+re.escape(year)+r'(?![\da-z])',re.I)
        for p in index['contexts']:
            if p['kind']=='head':continue
            for m in pattern.finditer(p['text']):
                if any(x['start']<=m.start()<x['end'] for x in p.get('bibliography_spans',[])):continue
                o=next((o for o in index['occurrences'] if o['paragraph_id']==p['id'] and o['offsets']['start'] is not None and o['offsets']['start']<m.end() and o['offsets']['end']>m.start()),None)
                if o is None:
                    start,end=envelope(p['text'],*m.span())
                    o=dict(location_id=uid('loc',index['document_id'],'joint_author',p['id'],start,end),raw_marker=p['text'][start:end],marker_source='local_joint_author_year_scan',paragraph_id=p['id'],offsets=dict(start=start,end=end,unit='unicode_codepoint',end_exclusive=True),coordinates=p.get('coordinates',[]),source_evidence_ids=[],links=[],human_review_status='not_reviewed',style='author_year',typography='unknown',carrier=p['kind'],expanded_numbers=[],unresolved_numbers=[])
                    index['occurrences'].append(o)
                if add_edge(index,o,r,'unique_local_joint_author_list_and_year'):
                    changes.append(dict(kind='recover_joint_author_citation',location_id=o['location_id'],reference_id=r['reference_id'],joint_authorship=joint))
    return changes


def recover_personal_authors(index):
    changes=[]
    for o in index['occurrences']:
        if o.get('style')!='author_year':continue
        for r in index['references']:
            if not r.get('organization_candidate') or not r.get('authors'):continue
            family=r['authors'][0].get('family','');year=r.get('year_label') or r.get('year')
            if not family or not year:continue
            # Full surname (including particles), not a loose surname token.
            name=r'\s+'.join(re.escape(x) for x in family.split())
            pattern=re.compile(r'(?<!\w)'+name+r'\s+(?:et\s+al\.?)\s*,?\s*'+re.escape(str(year))+r'(?![\da-z])',re.I)
            if not pattern.search(o['raw_marker']):continue
            possible=[b for b in index['references'] if b.get('authors') and
                      compact(b['authors'][0].get('family',''))==compact(family) and
                      str(b.get('year_label') or b.get('year'))==str(year)]
            if len(possible)!=1:
                index['review_queue'].append(dict(location_id=o['location_id'],reason='ambiguous_personal_author_year',candidate_reference_ids=[b['reference_id'] for b in possible]));continue
            if r['organization_candidate'].get('mixed_reference'):continue
            if add_edge(index,o,r,'full_personal_author_and_unique_year_in_local_bibliography'):
                changes.append(dict(kind='recover_personal_author_citation',location_id=o['location_id'],reference_id=r['reference_id'],marker=o['raw_marker']))
    return changes


def number_map(doc,index):
    """Read printed labels at exact bibliography coordinates. Never infer order+1."""
    found={};evidence={}
    for r in index['references']:
        cs=r.get('coordinates',[])
        if not cs:continue
        c=cs[0];page=doc[c['page']-1];box=pymupdf.Rect(c['x'],c['y'],c['x']+c['width'],c['y']+c['height'])
        for block in page.get_text('dict')['blocks']:
            for line in block.get('lines',[]):
                rect=pymupdf.Rect(line['bbox'])
                if abs(rect.y0-box.y0)>4 or (rect&box).get_area()/max(min(rect.get_area(),box.get_area()),.01)<.5:continue
                text=''.join(s['text'] for s in line['spans']);m=re.match(r'^\s*(?:[\[(](\d+)[\])]|(\d+)\.)\s*(.+)',text)
                if not m:
                    labels=[]
                    for bb in page.get_text('dict')['blocks']:
                        for ll in bb.get('lines',[]):
                            tt=''.join(ss['text'] for ss in ll['spans']).strip();rr=pymupdf.Rect(ll['bbox'])
                            if re.fullmatch(r'\d+\.',tt) and abs(rr.y0-rect.y0)<2 and 0<=rect.x0-rr.x1<40:labels.append(tt)
                    if len(labels)==1:m=re.match(r'^\s*(?:[\[(](\d+)[\])]|(\d+)\.)\s*(.+)',labels[0]+' '+text)
                if not m:continue
                prefix=compact(m[3])[:40]
                if len(prefix)<15 or not compact(r.get('raw_citation','')).startswith(prefix):continue
                n=int(m[1] or m[2]);found.setdefault(n,[]).append(r)
                evidence[n]=dict(page=c['page'],text=text,bbox=list(rect))
    return {n:rs[0] for n,rs in found.items() if len({r['reference_id'] for r in rs})==1},evidence


def recover_numeric(pdf,data,index):
    changes=[];findings=[]
    with pymupdf.open(pdf) as doc:
        mapping,labels=number_map(doc,index)
        for o in index['occurrences']:
            if o.get('style')!='numeric':continue
            for n in o.get('expanded_numbers',[]):
                r=mapping.get(n)
                if not r or not r.get('organization_candidate'):continue
                # Resolve only a missing number, never overwrite a conflicting parser link.
                if n not in o.get('unresolved_numbers',[]):continue
                if add_edge(index,o,r,'original_pdf_printed_reference_number'):
                    o['unresolved_numbers'].remove(n)
                    changes.append(dict(kind='recover_existing_numeric_marker',location_id=o['location_id'],reference_id=r['reference_id'],printed_number=n))
        groups=list(data.get('unlinked_numeric_pdf_groups',[]))
        for span in data.get('unlinked_superscript_candidates',[]):
            if not any(n in mapping and mapping[n].get('organization_candidate') for n in span.get('expanded_numbers',[])):continue
            page_no=span['page'];box=pymupdf.Rect(span['bbox']);page=doc[page_no-1]
            # First-page author superscripts and unit exponents are not citations.
            if page_no==1:continue
            if any(c['page']==page_no and (box&pymupdf.Rect(c['x'],c['y'],c['x']+c['width'],c['y']+c['height'])).get_area()>0 for r in index['references'] for c in r.get('coordinates',[])):continue
            before=page.get_text(clip=pymupdf.Rect(box.x0-18,box.y0-2,box.x0,box.y1+4)).rstrip()
            if re.search(r'(?:\d|[−+×]|\b(?:kg|cm|mm|mol|m|s))$',before):continue
            if not re.search(r'[A-Za-z]{3}',span.get('context','')) or len(span.get('context',''))<60:continue
            groups.append(dict(raw_marker=span['raw_marker'],expanded_numbers=span['expanded_numbers'],page=page_no,bboxes=[span['bbox']],source='original_pdf_superscript_unlinked'))
        for g in groups:
            targets=[mapping[n] for n in g['expanded_numbers'] if n in mapping and mapping[n].get('organization_candidate')]
            if not targets:continue
            page_no=g['page'];page=doc[page_no-1];box=pymupdf.Rect(g['bboxes'][0])
            if any(o['raw_marker']==g['raw_marker'] and any(c.get('page')==page_no and c.get('bbox')==g['bboxes'][0] for c in o['coordinates']) for o in index['occurrences']):continue
            # Exclude bibliography labels and obvious mathematical intervals.
            if any(page_no==e['page'] and abs(box.y0-e['bbox'][1])<3 for e in labels.values()):continue
            before=page.get_text(clip=pymupdf.Rect(box.x0-25,box.y0-1,box.x0,box.y1+1)).rstrip()
            if before.endswith(('∈','∉')):continue
            blocks=[b for b in page.get_text('blocks') if b[6]==0]
            block=next((b for b in blocks if (pymupdf.Rect(b[:4])&box).get_area()/max(box.get_area(),.01)>.7),None)
            if block is None:continue
            selected=[block]
            # First-page two-column continuation: right column starts lowercase,
            # left column ends incomplete in same vertical body band.
            if box.x0>page.rect.width/2 and re.match(r'^[a-z]',block[4].strip()):
                left=[b for b in blocks if b[2]<page.rect.width/2+8 and len(b[4])>100 and
                      block[1]-5<=b[1]<block[3] and abs(b[3]-block[3])<25 and
                      not re.search(r'[.!?:]\s*$',b[4])]
                if len(left)==1:selected=[left[0],block]
            raw='\n'.join(b[4].strip() for b in selected)
            matches=list(re.finditer(re.escape(g['raw_marker']),raw))
            boxes=[q for b in selected for q in page.search_for(g['raw_marker'],clip=pymupdf.Rect(b[:4]))]
            if len(matches)>1:
                if len(boxes)!=len(matches):
                    findings.append(dict(code='target_numeric_context_unresolved',page=page_no,marker=g['raw_marker'],reason='repeated_marker_offset_ambiguous'));continue
                at=max(range(len(boxes)),key=lambda i:(boxes[i]&box).get_area())
                pos=matches[at].start()
            else:pos=matches[0].start() if matches else -1
            if pos<0:
                findings.append(dict(code='target_numeric_context_unresolved',page=page_no,marker=g['raw_marker']));continue
            # Reuse an existing context if it fully contains this source block.
            context=next((c for c in index['contexts'] if compact(raw) in compact(c['text'])),None)
            if context is None:
                pid=uid('pdf_context',index['document_id'],page_no,[list(b[:4]) for b in selected])
                headings=[s for s in index['sections'] if s.get('title','').lower().endswith('introduction')]
                context=dict(id=pid,text=raw,kind='p',section_id=headings[0]['id'] if page_no==1 and len(headings)==1 else None,
                             coordinates=[coord(page_no,b[:4]) for b in selected],sentences=[],previous_paragraph_id=None,next_paragraph_id=None,
                             completeness='pdf_blocks_recovered_paragraph_boundary_not_certified',source='original_pdf_text_blocks')
                index['contexts'].append(context)
            else:
                pos=context['text'].find(g['raw_marker'])
                if pos<0:continue
            o=dict(location_id=uid('loc',index['document_id'],'recovered_numeric',page_no,g['bboxes']),raw_marker=g['raw_marker'],
                   marker_source='original_pdf_characters',paragraph_id=context['id'],offsets=dict(start=pos,end=pos+len(g['raw_marker']),unit='unicode_codepoint',end_exclusive=True),
                   coordinates=[dict(page=page_no,bbox=b,origin='top-left',unit='PDF point') for b in g['bboxes']],
                   source_evidence_ids=[],links=[],human_review_status='not_reviewed',style='numeric',typography='unknown',carrier='p',
                   expanded_numbers=g['expanded_numbers'],unresolved_numbers=[n for n in g['expanded_numbers'] if n not in mapping])
            for n in g['expanded_numbers']:
                if n in mapping:add_edge(index,o,mapping[n],'original_pdf_marker_and_printed_bibliography_label')
            index['occurrences'].append(o)
            changes.append(dict(kind='recover_missing_numeric_context',location_id=o['location_id'],raw_marker=g['raw_marker'],page=page_no,
                                bibliography_label_evidence=[labels[n] for n in g['expanded_numbers'] if n in labels],context_id=context['id']))
    return changes,findings


def recover_table_codes(pdf,data,index):
    changes=[]
    short=[re.escape(a['name']) for a in ALIASES['aliases'] if 2<=len(a['name'])<=12 and '/' not in a['name']]
    pattern=re.compile(r'(?<!\w)('+'|'.join(short)+r')\s*/\s*[A-Za-z][A-Za-z0-9.-]*(?:\s*/\s*[A-Za-z0-9][A-Za-z0-9.-]*){1,8}',re.I)
    document=data.get('docling',{}).get('document',{})
    with pymupdf.open(pdf) as doc:
        for table in document.get('tables',[]):
            for cell in table.get('data',{}).get('table_cells',[]):
                for hit in pattern.finditer(cell.get('text','')):
                    marker=hit.group().rstrip('.');provs=table.get('prov',[])
                    if not provs:continue
                    page_no=provs[0]['page_no'];page=doc[page_no-1];bbox=cell.get('bbox')
                    if not bbox:continue
                    box=pymupdf.Rect(bbox['l'],bbox['t'],bbox['r'],bbox['b'])
                    if bbox.get('coord_origin')=='BOTTOMLEFT':box=pymupdf.Rect(bbox['l'],page.rect.height-bbox['t'],bbox['r'],page.rect.height-bbox['b'])
                    text=page.get_text(clip=box+(-2,-2,2,2))
                    if compact(marker) not in compact(text):continue
                    row_no=cell['start_row_offset_idx'];cells=sorted([c for c in table['data']['table_cells'] if c['start_row_offset_idx']<=row_no<c['end_row_offset_idx']],key=lambda c:c['start_col_offset_idx'])
                    raw=' | '.join(c['text'] for c in cells);pos=raw.find(marker)
                    if pos<0:continue
                    ident=uid('source_code',index['document_id'],re.sub(r'\s+','',marker))
                    identity=org_reference({'raw_citation':hit.group(1)+'.'})
                    if not identity:continue
                    identity.update(evidence=['configured_organization_prefix_in_pdf_verified_document_identifier'],resource_type='document_identifier_unresolved',identity_status='candidate_document_identifier')
                    reference=dict(id=ident,reference_id=uid('ref',index['document_id'],ident),raw_citation=marker,title=None,year=None,year_label=None,authors=[],
                                   organization_candidate=identity,source='original_pdf_table_document_identifier',coordinates=[coord(page_no,box)],document_identifier=re.sub(r'\s+','',marker))
                    if not any(r['id']==ident for r in index['references']):index['references'].append(reference)
                    pid=uid('table_context',index['document_id'],table['self_ref'],row_no)
                    context=dict(id=pid,text=raw,kind='table',section_id=None,coordinates=[coord(page_no,box)],sentences=[],previous_paragraph_id=None,next_paragraph_id=None)
                    if not any(c['id']==pid for c in index['contexts']):index['contexts'].append(context)
                    o=dict(location_id=uid('loc',pid,pos,marker),raw_marker=marker,marker_source='original_pdf_verified_docling_table',paragraph_id=pid,
                           offsets=dict(start=pos,end=pos+len(marker),unit='unicode_codepoint',end_exclusive=True),coordinates=[coord(page_no,box)],source_evidence_ids=[table['self_ref']],links=[],
                           human_review_status='not_reviewed',style='document_identifier',typography='unknown',carrier='table',expanded_numbers=[],unresolved_numbers=[],docling_table_ids=[table['self_ref']])
                    if any(x['location_id']==o['location_id'] for x in index['occurrences']):continue
                    add_edge(index,o,reference,'pdf_verified_table_document_identifier');index['occurrences'].append(o)
                    changes.append(dict(kind='recover_table_document_identifier',location_id=o['location_id'],marker=marker,page=page_no,table_id=table['self_ref'],row=row_no))
    return changes


def recover(pdf,data,index):
    changes=recover_joint_authors(index)+recover_personal_authors(index)
    numeric,findings=recover_numeric(pdf,data,index);changes.extend(numeric)
    changes.extend(recover_table_codes(pdf,data,index))
    table_changes,table_pending=recover_fragmented_table_sources(pdf,index)
    changes.extend(table_changes);findings.extend(table_pending)
    linked={l['reference_id'] for o in index['occurrences'] for l in o['links']}
    index['bibliography_only_organization_candidates']=[r['id'] for r in index['references'] if r.get('organization_candidate') and r['reference_id'] not in linked]
    index['review_queue']=[q for q in index['review_queue'] if not(q.get('reason')=='no_link_or_unresolved_number' and any(o['location_id']==q.get('location_id') and o['links'] and not o['unresolved_numbers'] for o in index['occurrences']))]
    return changes,findings


def recover_fragmented_table_sources(pdf,index):
    """Printed four-column resource tables: row anchors + embedded PDF links.
    Administration alone stays an attribution candidate, never a citation edge.
    """
    from urllib.parse import urlsplit
    changes=[];pending=[]
    with pymupdf.open(pdf) as doc:
        for page_no,page in enumerate(doc,1):
            lines=[(''.join(s['text'] for s in l['spans']).strip(),pymupdf.Rect(l['bbox'])) for b in page.get_text('dict')['blocks'] for l in b.get('lines',[])]
            for title,header in lines:
                if title!='Reference':continue
                headers=[]
                for expected in ['Year','Administration','Link, description or']:
                    possible=[box for text,box in lines if text==expected and abs(box.y0-header.y0)<3 and box.x0>header.x0]
                    if not possible:break
                    headers.append(min(possible,key=lambda b:b.x0))
                if len(headers)!=3:continue
                year,admin,source=headers
                right=min(page.rect.width-25,header.x0+(page.rect.width-70)/2)
                anchors=sorted([box.y0 for text,box in lines if re.match(r'^(?:18|19|20)\d{2}(?:\s*&)?$',text) and abs(box.x0-year.x0)<3 and box.y0>header.y1])
                for row_num,(top,bottom) in enumerate(zip(anchors,anchors[1:]+[page.rect.height-40])):
                    # Collect full lines, in each printed column, without using reading order.
                    bounds=[header.x0-2,year.x0-2,admin.x0-2,source.x0-2,right]
                    cells=[]
                    for a,b in zip(bounds,bounds[1:]):
                        items=sorted([(box.y0,text) for text,box in lines if a<=box.x0<b and top-1<=box.y0<bottom-1],key=lambda x:x[0])
                        cells.append(' '.join(t for _,t in items))
                    if not cells[0] or not re.search(r'(?<!\w)'+ORG+r'(?!\w)', ' '.join(cells),re.I):continue
                    links=[l for l in page.get_links() if l.get('uri') and source.x0-2<=l['from'].x0<right and top-1<=l['from'].y0<bottom-1]
                    urls=list(dict.fromkeys(l['uri'] for l in links if any((urlsplit(l['uri']).hostname or '').lower()==domain or (urlsplit(l['uri']).hostname or '').lower().endswith('.'+domain) for domain in ALIASES.get('domains',['unep.org'] if ALIASES['organization_id']=='UNEP' else []))))
                    rowbox=pymupdf.Rect(header.x0,top,right,min(bottom,page.rect.height-40))
                    evidence=dict(page=page_no,row_text=' | '.join(cells),cells=cells,coordinates=[coord(page_no,rowbox)],pdf_link_urls=list(dict.fromkeys(l['uri'] for l in links)))
                    if not urls and any(r.get('source')=='original_pdf_table_document_identifier' and compact(r.get('raw_citation','')) in compact(cells[3]) and page_no in {c['page'] for c in r.get('coordinates',[])} for r in index['references']):continue
                    if not urls:
                        pending.append(dict(code='table_organization_role_requires_classification',**evidence));continue
                    primary=max(urls,key=len);raw=cells[3]+' '+primary;ident=uid('table_web_ref',index['document_id'],page_no,round(top,2))
                    identity=org_reference({'raw_citation':raw})
                    if not identity:continue
                    identity.update(year_label_from_raw=None,resource_type='web_resource_from_table_source',evidence=['official_domain_in_original_pdf_table_source_hyperlink'])
                    reference=dict(id=ident,reference_id=uid('ref',index['document_id'],ident),raw_citation=raw,title=cells[0],authors=[],year=None,year_label=None,
                                   organization_candidate=identity,coordinates=[coord(page_no,rowbox)],source='original_pdf_table_source_hyperlink',source_urls=urls)
                    if any(r['id']==ident for r in index['references']):continue
                    index['references'].append(reference);pid=uid('table_row',index['document_id'],page_no,round(top,2));context=evidence['row_text'];start=context.rfind(cells[3])
                    index['contexts'].append(dict(id=pid,text=context,kind='table',section_id=None,coordinates=evidence['coordinates'],sentences=[],previous_paragraph_id=None,next_paragraph_id=None))
                    o=dict(location_id=uid('loc',pid,'source'),raw_marker=cells[3],marker_source='original_pdf_table_hyperlink',paragraph_id=pid,
                           offsets=dict(start=start,end=start+len(cells[3]),unit='unicode_codepoint',end_exclusive=True),coordinates=evidence['coordinates'],source_evidence_ids=[],links=[],
                           human_review_status='not_reviewed',style='source_url',typography='unknown',carrier='table',expanded_numbers=[],unresolved_numbers=[])
                    add_edge(index,o,reference,'printed_table_row_and_official_source_hyperlink');index['occurrences'].append(o)
                    changes.append(dict(kind='recover_fragmented_table_web_source',location_id=o['location_id'],**evidence))
    return changes,pending
