"""Recover omitted target references from Docling, verified against original PDF regions."""
import difflib
import hashlib
import re
import unicodedata
import pymupdf
from pdf_evidence import open_document
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
    raw=item['text'].strip();whole=presence_text(raw)
    apa_date=re.search(r'\(\s*((?:19|20)\d{2}[a-z]?)\s*\)',raw[:240])
    if number is None and not apa_date:return None
    fragments=[b for b in data['bibliography'] if b.get('raw_citation') and presence_text(b['raw_citation']) in whole]
    fragments=[b for b in fragments if b.get('coordinates') and all(any(c['page']==r['page'] and c['x']>=r['x']-2 and c['y']>=r['y']-2 and c['x']+c['width']<=r['x']+r['width']+2 and c['y']+c['height']<=r['y']+r['height']+2 for r in coords) for c in b['coordinates'])]
    if len(fragments)<2:return None
    fragments.sort(key=lambda b:whole.index(presence_text(b['raw_citation'])))
    if ''.join(presence_text(b['raw_citation']) for b in fragments)!=whole:return None
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
    if apa_date:
        reference.update(year=apa_date[1][:4],year_label=apa_date[1],title=re.split(r'\.\s+',raw[apa_date.end():].lstrip(' .,'),maxsplit=1)[0])
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


def native_numbered_entry(doc,coords):
    """Re-extract a damaged Docling item only inside its original PDF region."""
    if len(coords)!=1:return None
    c=coords[0];rect=pymupdf.Rect(c['x'],c['y'],c['x']+c['width'],c['y']+c['height'])
    lines=[]
    for block in doc[c['page']-1].get_text('dict')['blocks']:
        for line in block.get('lines',[]):
            box=pymupdf.Rect(line['bbox'])
            if (box&rect).get_area()/max(box.get_area(),.01)>.65:lines.append((box.y0,box.x0,''.join(s['text'] for s in line['spans'])))
    raw='\n'.join(x[2] for x in sorted(lines)).strip()
    numbered=re.match(r'^\s*(\((\d+)\)|\[(\d+)\])\s*(.+)',raw,re.S)
    if not numbered or re.search(r'\n\s*(?:\(\d+\)|\[\d+\])',raw):return None
    text=' '.join(numbered[4].split())
    if not ORG_PREFIX.match(text):return None
    if not re.search(r'[,;]\s*(?:19|20)\d{2}\.\s*$',text):return None
    return text,numbered[1],raw


def recover(pdf,data):
    document=data.get('docling',{}).get('document',{})
    audit={'scope':'target entries in detected Docling bibliography','status':'unavailable','entries':[]}
    data['reference_region_audit']=audit
    if not document:return []
    existing=[compact(b.get('raw_citation') or '') for b in data['bibliography']]
    changes=[];in_references=False;seen_references=False
    with open_document(pdf) as doc:
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
                in_references=bool(re.fullmatch(r'(?:\d+[.\s]*)?(?:references|bibliography|works cited|参考文献)',raw.strip(' ■▪●◆•:：'),re.I))
                if in_references:audit['status']='checked';seen_references=True
                continue
            if item.get('label') not in {'list_item','text','reference'}:continue
            # A printed number may be fused into Docling's text, not its marker.
            inline_label=re.match(r'^(\d{1,3}\.)\s*(?=[A-Z])',raw)
            if inline_label and not item.get('marker'):
                raw=raw[inline_label.end():]
                item=dict(item,text=raw,marker=inline_label[1])
            if not in_references:
                # Two-column end matter may interleave publisher notes into the
                # reference reading order. Require an independent GROBID region.
                anchored=False
                if seen_references:
                    for prov in item.get('prov',[]):
                        n=prov.get('page_no');bb=prov.get('bbox',{})
                        if not n or not 1<=n<=len(doc) or not {'l','t','r','b'}<=bb.keys():continue
                        box=pymupdf.Rect(bb['l'],doc[n-1].rect.height-bb['t'],bb['r'],doc[n-1].rect.height-bb['b']) if bb.get('coord_origin')=='BOTTOMLEFT' else pymupdf.Rect(bb['l'],bb['t'],bb['r'],bb['b'])
                        for ref in data['bibliography']:
                            for c in ref.get('coordinates',[]):
                                r=pymupdf.Rect(c['x'],c['y'],c['x']+c['width'],c['y']+c['height'])
                                if c['page']==n and (r&box).get_area()>r.get_area()*.65:anchored=True
                if not anchored:continue
            if not org_reference({'raw_citation':raw}):continue
            entry={'docling_self_ref':item['self_ref'],'raw_reference':raw,'status':'unresolved','reason':'unsupported_author_year_structure'}
            audit['entries'].append(entry)
            match=ORG_YEAR.match(raw)
            if not match and 'target_in_place_publisher_field' in org_reference({'raw_citation':raw})['evidence']:
                match=re.match(r'^([^()]{2,80})\(\s*((?:19|20)\d{2}[a-z]?)\s*\)',raw)
            if not match and raw.startswith('United Nations.'):
                match=re.match(r'^(United Nations)\.\s*((?:19|20)\d{2}[a-z]?)\b',raw)
            trailing_author=ORG_PREFIX.match(raw) if re.search(r',\s*(?:19|20)\d{2}[a-z]?\.\s*$',raw) else None
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
            if not present:
                contained=[b for b in data['bibliography'] if len(presence_text(b.get('raw_citation','')))>=40 and presence_text(b['raw_citation']) in presence_text(raw)]
                contained.sort(key=lambda b:presence_text(raw).index(presence_text(b['raw_citation'])))
                if len(contained)>1 and not item.get('marker') and all(re.search(r'\(\s*(?:19|20)\d{2}[a-z]?\s*\)',b.get('raw_citation','')[:240]) for b in contained) and ''.join(presence_text(b['raw_citation']) for b in contained)==presence_text(raw) and presence_text(raw) in presence_text(' '.join(evidence)):
                    entry.update(status='present',reason='pdf_verified_container_of_existing_references',reference_ids=[b['id'] for b in contained],pdf_text_evidence=evidence)
                    for b in contained:
                        for p in data['paragraphs']:mark_reference_span(p,b['raw_citation'],item['self_ref'])
                    continue
            if present:
                entry.update(status='present', reason='matched_existing_reference_at_verified_pdf_location',
                             reference_id=present['id'], pdf_text_evidence=evidence,
                             verification_scope='existing_reference_presence_only')
                # Correct only an absent/author-only title after independent
                # region verification; retain the original parser object.
                author=ORG_PREFIX.match(raw)
                old_title=present.get('title') or ''
                if author and (not old_title or presence_text(old_title)==presence_text(author[1])):
                    tail=raw[author.end():]
                    if tail.startswith('.') and re.search(r'[,;.]\s*(?:19|20)\d{2}\.?\s*$',raw):
                        title=re.split(r'\.\s+',tail.lstrip('. '),maxsplit=1)[0].strip(' .')
                        if len(title)>=8 and not re.fullmatch(r'(?:19|20)\d{2}',title):
                            present['title']=title
                            changes.append(dict(kind='repair_author_only_reference_title',reference_id=present['id'],original_title=old_title,title=title,pdf_text_evidence=evidence,method='verified_author_period_title_period_publisher_year'))
                for p in data['paragraphs']:mark_reference_span(p,present['raw_citation'],item['self_ref'])
                continue
            if not coords or (compact(raw) not in compact(' '.join(evidence)) and not (len(presence_text(raw))>=60 and presence_text(raw) in presence_text(' '.join(evidence)))):
                native=native_numbered_entry(doc,coords)
                if not native:
                    entry['reason']='original_pdf_text_not_verified';continue
                raw,marker,pdf_text=native;item=dict(item,text=raw,marker=marker);evidence=[pdf_text]
                entry['docling_text_before_repair']=entry['raw_reference'];entry['raw_reference']=raw
                entry['native_text_recovery']='original_pdf_numbered_entry_with_target_author_and_trailing_year'
                match=ORG_YEAR.match(raw)
                title=raw
            marker=item.get('marker','')
            number_match=re.fullmatch(r'(?:[\[(](\d+)[\])]|(\d+)\.)',marker)
            printed_number=int(number_match.group(1) or number_match.group(2)) if number_match and presence_text(marker+raw) in presence_text(' '.join(evidence)) else None
            joined=join_split_reference(data,item,coords,evidence,printed_number)
            if joined:
                changes.append(joined);entry.update(status='recovered',reason='joined_pdf_verified_reference_fragments',reference_id=joined['reference']['id'])
                existing=[compact(b.get('raw_citation') or '') for b in data['bibliography']]
                for p in data['paragraphs']:mark_reference_span(p,raw,item['self_ref'])
                continue
            for p in data['paragraphs']:mark_reference_span(p,raw,item['self_ref'])
            normalized=compact(raw)
            # Existing or merged original entries retain their own repair logic.
            embedded=[b for b in data['bibliography'] if len(presence_text(b.get('raw_citation','')))>len(presence_text(raw))+40 and presence_text(raw) in presence_text(b.get('raw_citation',''))]
            exact=any(same_identifying_text(raw,b.get('raw_citation','')) for b in data['bibliography'])
            if exact:
                entry.update(status='present',reason='matched_existing_reference');continue
            # A separately bounded, PDF-verified target entry inside a merged
            # parser reference needs its own identity, not a 'present' shortcut.
            if any(normalized in e for e in existing if e) and not ((match or trailing_author) and len(embedded)==1):
                entry.update(status='present',reason='matched_existing_reference');continue
            trailing=None
            if not match:
                # Numbered title-first citations may print publication year last.
                trailing=re.search(r'[,;.]\s*((?:19|20)\d{2}[a-z]?)\s*[.)]?\s*(?:$|Available online:|https?://)',raw)
                if (printed_number is None and not trailing_author) or not trailing:
                    entry['reason']='unsupported_author_year_structure';continue
                title=raw[:trailing.start()].strip(' ;,.')
            if len(title)<8:
                entry['reason']='insufficient_title';continue
            ident='docling_ref_'+hashlib.sha256((item['self_ref']+'\0'+raw).encode()).hexdigest()[:16]
            label=(match.group(2) if match else trailing.group(1)).lower();year=label[:4] if label[:4].isdigit() else None
            reference={'id':ident,'raw_citation':raw,'year':year,'year_label':label,'title':title,'authors':[],
                       'raw_author_prefix':match.group(1) if match else None,'numeric_label':printed_number,'coordinates':coords,
                       'source':'docling_reference_region_verified_in_pdf','docling_self_ref':item['self_ref']}
            if not org_reference(reference):
                entry['reason']='target_identity_not_verified';continue
            entry.update(status='recovered',reason='verified_in_original_pdf',reference_id=ident)
            if (match or trailing_author) and len(embedded)==1:
                embedded[0]['target_identity_excluded_due_to_verified_subentry']=True
                embedded[0].setdefault('verified_target_subentries',[]).append(ident)
                reference['recovered_from_merged_reference_id']=embedded[0]['id']
                if match:
                    author=re.escape(match.group(1).strip()).replace(r'\ ',r'\s+')
                    marker_pattern=re.compile(r'(?<!\w)'+author+r'\s*[, (]\s*'+re.escape(label)+r'(?![\da-z])',re.I)
                    for mention in data['citation_mentions']:
                        if embedded[0]['id'] in mention.get('target_ids',[]) and marker_pattern.search(mention['raw_marker']):
                            mention['target_ids']=list(dict.fromkeys(mention['target_ids']+[ident]))
                            mention.setdefault('links',[]).append(dict(target_id=ident,method='pdf_verified_subentry_local_author_and_year',confidence=None))
            data['bibliography'].append(reference);existing.append(normalized)
            changes.append({'kind':'recover_omitted_reference','method':'docling_reference_section_and_original_pdf_text',
                            'source_sha256':data['source']['sha256'],'docling_self_ref':item['self_ref'],
                            'reference':reference,'pdf_text_evidence':evidence})
    if any(e['status']=='unresolved' for e in audit['entries']):audit['status']='needs_attention'
    elif any(e['status']=='recovered' for e in audit['entries']):audit['status']='repaired'
    return changes
