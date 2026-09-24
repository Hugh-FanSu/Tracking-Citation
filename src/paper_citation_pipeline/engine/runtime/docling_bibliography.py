"""Recover omitted target references from Docling, verified against original PDF regions."""
import difflib
import hashlib
import re
import unicodedata
import pymupdf
from standardize_citations import ORG_PREFIX,ORG_YEAR,org_reference


def compact(text):
    return ''.join('-' if unicodedata.category(c)=='Pd' or c=='−' else c for c in unicodedata.normalize('NFKC',text).casefold() if not c.isspace() and c!='\u00ad')


def presence_text(text):
    # Presence reconciliation only: never used as evidence to create a reference.
    return ''.join(c for c in unicodedata.normalize('NFKD', text).casefold() if c.isalnum() and c not in 'ˆ˜')


def same_identifying_text(left, right):
    left, right = presence_text(left), presence_text(right)
    if len(left) < 60 or len(right) < 60:
        return False
    if left == right:
        return True
    # At most one alphabetic character lost/substituted, with matching leading
    # author text and unchanged numbers (years, report IDs and DOI digits).
    if left[:40] != right[:40] or re.findall(r'\d+', left) != re.findall(r'\d+', right):
        return False
    edits = [op for op in difflib.SequenceMatcher(None, left, right, autojunk=False).get_opcodes() if op[0] != 'equal']
    return len(edits) == 1 and max(edits[0][2]-edits[0][1], edits[0][4]-edits[0][3]) == 1


def existing_at_verified_location(bibliography, raw, coords, evidence):
    """Recognize a present entry; cannot recover, replace or link references."""
    found = []
    for reference in bibliography:
        original = reference.get('raw_citation', '')
        locations = reference.get('coordinates', [])
        if not locations or not same_identifying_text(raw, original):
            continue
        # Every original line must be enclosed by the independent Docling region.
        if not all(any(c['page'] == r['page'] and c['x'] >= r['x']-2 and
                       c['y'] >= r['y']-2 and c['x']+c['width'] <= r['x']+r['width']+2 and
                       c['y']+c['height'] <= r['y']+r['height']+2 for r in coords) for c in locations):
            continue
        pdf_text = ' '.join(evidence)
        # Printed list labels may precede the raw entry. Keep the raw entry's
        # complete normalized text, including its identifying numbers.
        normalized_pdf, normalized_original = presence_text(pdf_text), presence_text(original)
        if normalized_original not in normalized_pdf:
            continue
        found.append(reference)
    return found[0] if len(found) == 1 else None


def reading_items(document):
    seen=set()
    def walk(ref):
        key=ref.get('$ref') if isinstance(ref,dict) else ref
        if not key or key in seen:return
        seen.add(key)
        node=document
        try:
            for part in key.lstrip('#/').split('/'):node=node[int(part)] if isinstance(node,list) else node[part]
        except (KeyError,IndexError,ValueError,TypeError):return
        if node.get('text') is not None:yield node
        for child in node.get('children',[]):yield from walk(child)
    yield from walk('#/body')


def mark_reference_span(paragraph,raw,source):
    # Keep original paragraph text/offsets; only exclude this bibliographic span from citation scanning.
    chars=[];positions=[]
    for i,c in enumerate(paragraph['text']):
        for normalized in compact(c):chars.append(normalized);positions.append(i)
    normalized=''.join(chars);needle=compact(raw);start=normalized.find(needle)
    while needle and start>=0:
        end=start+len(needle)
        item={'start':positions[start],'end':positions[end-1]+1,'source':source,'reason':'verified_docling_bibliography_entry'}
        if item not in paragraph.setdefault('bibliography_spans',[]):paragraph['bibliography_spans'].append(item)
        start=normalized.find(needle,end)


def join_split_reference(data,item,coords,evidence,number):
    if number is None:return None
    raw=item['text'].strip();whole=compact(raw)
    fragments=[b for b in data['bibliography'] if b.get('raw_citation') and compact(b['raw_citation']) in whole]
    if len(fragments)<2:return None
    fragments.sort(key=lambda b:whole.index(compact(b['raw_citation'])))
    if ''.join(compact(b['raw_citation']) for b in fragments)!=whole:return None
    # Every fragment must occupy the same PDF region as the verified complete entry.
    for b in fragments:
        if not b.get('coordinates'):return None
        for c in b['coordinates']:
            if not any(c['page']==r['page'] and c['x']>=r['x']-2 and c['y']>=r['y']-2 and
                       c['x']+c['width']<=r['x']+r['width']+2 and c['y']+c['height']<=r['y']+r['height']+2 for r in coords):return None
    first=fragments[0];ident=first['id'];ids={b['id'] for b in fragments}
    reference=dict(first,raw_citation=raw,numeric_label=number,coordinates=coords,
                   source='docling_numbered_reference_verified_in_pdf',docling_self_ref=item['self_ref'],
                   joined_original_ids=[b['id'] for b in fragments])
    author=ORG_PREFIX.match(raw)
    if author and '|' in raw:
        reference['title']=raw[author.end():].lstrip(' .,').split('|',1)[0].strip()
    # A year at the end of the bibliographic title/publisher clause is distinct from report coverage years.
    date=re.search(r',\s*((?:19|20)\d{2})\.\s*[〈<]?https?://',raw)
    if date:reference.update(year=date.group(1),year_label=date.group(1),publication_year_source='pdf_verified_trailing_year_before_url')
    data['bibliography']=[reference if b['id']==ident else b for b in data['bibliography'] if b['id']==ident or b['id'] not in ids]
    def remap(values):return list(dict.fromkeys(ident if x in ids else x for x in values))
    for m in data['citation_mentions']:
        for key in ('target_ids','grobid_targets','candidate_target_ids','invalid_targets'):
            if key in m:m[key]=remap(m[key])
        for link in m.get('links',[]):
            if link['target_id'] in ids:link.update(target_id=ident,method='pdf_verified_reference_fragment_join')
        for target in m.get('numeric_targets',[]):
            if target.get('target_id') in ids:target['target_id']=ident
    for g in data.get('pdf_citation_groups',[])+data.get('recovered_pdf_table_citation_groups',[]):
        for target in g.get('numeric_targets',[]):target['target_ids']=remap(target['target_ids'])
    return {'kind':'join_split_reference','method':'docling_complete_entry_and_original_pdf_number_and_text',
            'source_sha256':data['source']['sha256'],'original_fragments':fragments,'reference':reference,
            'pdf_text_evidence':evidence,'docling_self_ref':item['self_ref']}


def recover(pdf,data):
    document=data.get('docling',{}).get('document',{})
    audit={'scope':'target entries in detected Docling bibliography','status':'unavailable','entries':[]}
    data['reference_region_audit']=audit
    if not document:return []
    existing=[compact(b.get('raw_citation') or '') for b in data['bibliography']]
    changes=[];in_references=False
    with pymupdf.open(pdf) as doc:
        # Docling can mislabel repeated page headers as section headings.
        margins={}
        for text in document.get('texts',[]):
            for prov in text.get('prov',[]):
                page=prov.get('page_no');box=prov.get('bbox',{})
                if not page or not 1<=page<=len(doc) or 't' not in box:continue
                h=doc[page-1].rect.height;top=h-box['t'] if box.get('coord_origin')=='BOTTOMLEFT' else box['t']
                if top<.08*h or top>.92*h:margins.setdefault(compact(text.get('text','')),set()).add(page)
        running_headers={text for text,pages in margins.items() if len(pages)>1}
        for item in reading_items(document):
            raw=item['text'].strip()
            if item.get('label')=='section_header':
                if compact(raw) in running_headers:continue
                in_references=bool(re.fullmatch(r'(?:\d+[.\s]*)?(?:references|bibliography|works cited|参考文献)',raw,re.I))
                if in_references:audit['status']='checked'
                continue
            if not in_references or item.get('label') not in {'list_item','text','reference'}:continue
            if not org_reference({'raw_citation':raw}):continue
            entry={'docling_self_ref':item['self_ref'],'raw_reference':raw,'status':'unresolved','reason':'unsupported_author_year_structure'}
            audit['entries'].append(entry)
            match=ORG_YEAR.match(raw)
            title=re.split(r'\.\s+',raw[match.end():].lstrip(')., ') if match else raw,maxsplit=1)[0]
            coords=[];evidence=[]
            for prov in item.get('prov',[]):
                n=prov.get('page_no');box=prov.get('bbox',{})
                if not n or not 1<=n<=len(doc) or not {'l','t','r','b'}<=box.keys():continue
                page=doc[n-1]
                if box.get('coord_origin')=='BOTTOMLEFT':rect=pymupdf.Rect(box['l'],page.rect.height-box['t'],box['r'],page.rect.height-box['b'])
                else:rect=pymupdf.Rect(box['l'],box['t'],box['r'],box['b'])
                clipped=page.get_text(clip=rect+(-1,-1,1,1))
                evidence.append(clipped)
                coords.append({'page':n,'x':rect.x0,'y':rect.y0,'width':rect.width,'height':rect.height,'origin':'top-left','unit':'PDF point'})
            present = existing_at_verified_location(data['bibliography'], raw, coords, evidence)
            if present:
                entry.update(status='present', reason='matched_existing_reference_at_verified_pdf_location',
                             reference_id=present['id'], pdf_text_evidence=evidence,
                             verification_scope='existing_reference_presence_only')
                for p in data['paragraphs']:mark_reference_span(p,present['raw_citation'],item['self_ref'])
                continue
            if not coords or compact(raw) not in compact(' '.join(evidence)):
                entry['reason']='original_pdf_text_not_verified';continue
            marker=item.get('marker','')
            number_match=re.fullmatch(r'\[(\d+)\]',marker)
            printed_number=int(number_match.group(1)) if number_match and compact(marker+raw) in compact(' '.join(evidence)) else None
            joined=join_split_reference(data,item,coords,evidence,printed_number)
            if joined:
                changes.append(joined);entry.update(status='recovered',reason='joined_pdf_verified_reference_fragments',reference_id=joined['reference']['id'])
                existing=[compact(b.get('raw_citation') or '') for b in data['bibliography']]
                for p in data['paragraphs']:mark_reference_span(p,raw,item['self_ref'])
                continue
            for p in data['paragraphs']:mark_reference_span(p,raw,item['self_ref'])
            normalized=compact(raw)
            # Existing or merged original entries retain their own repair logic.
            if any(normalized in e for e in existing if e):
                entry.update(status='present',reason='matched_existing_reference');continue
            if not match:
                entry['reason']='unsupported_author_year_structure';continue
            if len(title)<8:
                entry['reason']='insufficient_title';continue
            ident='docling_ref_'+hashlib.sha256((item['self_ref']+'\0'+raw).encode()).hexdigest()[:16]
            label=match.group(2).lower();year=label[:4] if label[:4].isdigit() else None
            reference={'id':ident,'raw_citation':raw,'year':year,'year_label':label,'title':title,'authors':[],
                       'raw_author_prefix':match.group(1),'numeric_label':None,'coordinates':coords,
                       'source':'docling_reference_region_verified_in_pdf','docling_self_ref':item['self_ref']}
            if not org_reference(reference):
                entry['reason']='target_identity_not_verified';continue
            entry.update(status='recovered',reason='verified_in_original_pdf',reference_id=ident)
            data['bibliography'].append(reference);existing.append(normalized)
            changes.append({'kind':'recover_omitted_reference','method':'docling_reference_section_and_original_pdf_text',
                            'source_sha256':data['source']['sha256'],'docling_self_ref':item['self_ref'],
                            'reference':reference,'pdf_text_evidence':evidence})
    if any(e['status']=='unresolved' for e in audit['entries']):audit['status']='needs_attention'
    elif any(e['status']=='recovered' for e in audit['entries']):audit['status']='repaired'
    return changes
