"""Local resource-name evidence and a separate policy-borrowing review queue."""
import re
import pymupdf
from standardize_citations import uid,ORG
from target_recovery import compact,coord,add_edge


def resource_names(ref):
    title=ref.get('title') or ''
    return [m.group().strip() for m in re.finditer(r'\b(?:World\s+)?Database\s+(?:on|of|for)\s+(?:[A-Z][a-z]+\s*){1,6}',title)]


def recover_local_sources(pdf,index):
    changes=[];findings=[]
    refs=[r for r in index['references'] if r.get('organization_candidate') and not r['organization_candidate'].get('mixed_reference') and r.get('coordinates')]
    linked={e['reference_id'] for o in index['occurrences'] for e in o['links']}
    for r in index['references']:
        if r['reference_id'] in linked and not r.get('organization_candidate') and not r.get('target_identity_excluded_due_to_verified_subentry') and re.search(r'(?<!\w)'+ORG+r'(?!\w)',r.get('title') or '',re.I):
            findings.append(dict(code='target_in_title_author_role_requires_review',reference_id=r['reference_id'],raw_reference=r['raw_citation'],reason='Target name in cited title alone does not establish institutional authorship'))
    resources={}
    for r in refs:
        for name in resource_names(r):
            key=re.sub(r'\b(?:on|of)\b','on',name.lower());resources.setdefault(key,[]).append(r)
    with pymupdf.open(pdf) as doc:
        for page_no,page in enumerate(doc,1):
            for block in page.get_text('blocks'):
                if block[6]!=0:continue
                raw=block[4].strip();text=re.sub(r'\s+',' ',raw);box=pymupdf.Rect(block[:4])
                if any(c['page']==page_no and (pymupdf.Rect(c['x'],c['y'],c['x']+c['width'],c['y']+c['height'])&box).get_area()>0 for r in index['references'] for c in r.get('coordinates',[])):continue
                contexts={p['id']:p for p in index['contexts']}
                target_ids={r['reference_id'] for r in refs}
                if re.search(r'\b(?:modeled after|modelled after|inspired by|adapted from)\b',text,re.I):
                    possible=[]
                    for r in refs:
                        match=re.search(r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,4})\s+(?:on|for|of)\b',r.get('title') or '')
                        if match and match[1] in text:possible.append(r['reference_id'])
                    if possible:findings.append(dict(code='policy_source_use_requires_review',page=page_no,text=raw,coordinates=[coord(page_no,block[:4])],candidate_reference_ids=possible,reason='Unmarked policy borrowing; no confirmed citation edge created'))
                if any(any(e['reference_id'] in target_ids for e in o['links']) and compact(text) in compact(contexts.get(o['paragraph_id'],{}).get('text','')) for o in index['occurrences']):continue
                if re.search(r'(?<!\w)'+ORG+r'(?!\w)',text,re.I) and re.search(r'\b(?:convention|protocol)\b',text,re.I) and re.search(r'\b(?:entered into force|objective|requires)\b',text,re.I):
                    findings.append(dict(code='organization_policy_attribution_requires_review',page=page_no,text=raw,coordinates=[coord(page_no,block[:4])],reason='Named policy content without an explicit linked citation; source and authorship require classification'))
                if not re.search(r'\b(?:Using|We used|we used|we obtained)\b',text):continue
                if re.search(r'\b(?:not used|did not use|without using)\b',text,re.I):continue
                normalized=re.sub(r'\b(?:on|of)\b','on',text.lower())
                for name,possible in resources.items():
                    if not any(name in re.sub(r'\b(?:on|of)\b','on',sentence.lower()) and re.search(r'\b(?:Using|We used|we used|we obtained)\b',sentence) for sentence in re.split(r'(?<=[.!?])\s+',text)):continue
                    if any(not r.get('organization_candidate') and any(re.sub(r'\b(?:on|of)\b','on',n.lower())==name for n in resource_names(r)) for r in index['references']):continue
                    # Database identity is local; edition is not inferred from a bare name.
                    ids=sorted({r['reference_id'] for r in possible});ident=uid('local_resource',index['document_id'],page_no,list(block[:4]),name)
                    if any(r['id']==ident for r in index['references']):continue
                    identity=dict(possible[0]['organization_candidate']);identity.update(year_label_from_raw=None,resource_type='explicit_data_source_attribution',evidence=['resource_name_linked_to_local_target_bibliography'])
                    evidence=dict(text=raw,coordinates=[coord(page_no,block[:4])],local_reference_ids=ids,resource_name=name,edition_inferred=False)
                    ref=dict(id=ident,reference_id=uid('ref',ident),raw_citation=raw,title=None,authors=[],year=None,coordinates=[],organization_candidate=identity,source='original_pdf_local_resource_name',source_urls=[],attribution_evidence=evidence)
                    index['references'].append(ref);pid=uid('context',ident)
                    index['contexts'].append(dict(id=pid,text=raw,kind='abstract' if page_no==1 and box.width>.65*page.rect.width else 'p',section_id=None,coordinates=evidence['coordinates'],sentences=[],previous_paragraph_id=None,next_paragraph_id=None))
                    o=dict(location_id=uid('loc',ident),raw_marker='',marker_source='original_pdf_local_resource_name',citation_form='explicit_source_use_without_marker',paragraph_id=pid,offsets=dict(start=None,end=None,unit='unicode_codepoint',end_exclusive=True),coordinates=evidence['coordinates'],source_evidence_ids=ids,links=[],human_review_status='not_reviewed',style='attribution',typography='not_applicable',carrier='p',expanded_numbers=[],unresolved_numbers=[])
                    add_edge(index,o,ref,'local_resource_name_and_explicit_usage');o['links'][0]['link_status']='explicit_source_attribution';index['occurrences'].append(o)
                    changes.append(dict(kind='recover_local_resource_usage',location_id=o['location_id'],evidence=evidence))
    return changes,findings
