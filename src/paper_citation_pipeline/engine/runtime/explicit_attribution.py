"""Evidence-backed data use with no formal citation marker, from original PDF blocks."""
import re
from urllib.parse import urlsplit
import pymupdf
from standardize_citations import ORG,ALIASES,uid
from target_recovery import compact,coord,add_edge

TARGET=re.compile(r'(?<!\w)('+ORG+r')(?!\w)',re.I)
RESOURCE=re.compile(r'\b(?:data(?:base|sets?)?|plume\s+(?:list|database)|data\s+platform)\b',re.I)
USE=re.compile(r'\b(?:we\s+(?:\w+\s+){0,4}(?:used|use|performed|compiled|annotated)|datasets?\s+used|provided\s+a\s+benchmark|using\b)',re.I)


def recover(pdf,index):
    changes=[]
    with pymupdf.open(pdf) as doc:
        for page_no,page in enumerate(doc,1):
            for block in page.get_text('blocks'):
                if block[6]!=0:continue
                raw=block[4].strip();flat=re.sub(r'\s+',' ',raw);hit=TARGET.search(flat)
                if not hit or not USE.search(flat):continue
                # Usage and target ownership must occur in the same sentence.
                sentences=re.split(r'(?<=[.!?])\s+(?=[A-Z])',flat)
                eligible=[]
                for sentence in sentences:
                    m=TARGET.search(sentence)
                    if m and USE.search(sentence) and RESOURCE.search(sentence[max(0,m.start()-100):m.end()+180]):eligible.append(sentence)
                if not eligible:continue
                phrase=eligible[0]
                if re.search(r'\b(?:not\s+used|did\s+not\s+use|without\s+using)\b',flat,re.I):continue
                box=pymupdf.Rect(block[:4])
                if any(c['page']==page_no and (pymupdf.Rect(c['x'],c['y'],c['x']+c['width'],c['y']+c['height'])&box).get_area()>0 for r in index['references'] for c in r.get('coordinates',[])):continue
                # A numbered target citation already covering this block is not a second use.
                target_ids={r['reference_id'] for r in index['references'] if r.get('organization_candidate')}
                contexts={p['id']:p for p in index['contexts']}
                if any(any(e['reference_id'] in target_ids for e in o['links']) and compact(flat) in compact(contexts.get(o['paragraph_id'],{}).get('text','')) for o in index['occurrences']):continue
                ident=uid('attribution_ref',index['document_id'],page_no,list(block[:4]))
                if any(r['id']==ident for r in index['references']):continue
                urls=list(dict.fromkeys(l['uri'] for l in page.get_links() if l.get('uri') and (l['from']&box).get_area()>0 and compact(l['uri']) in compact(phrase) and TARGET.search(urlsplit(l['uri']).hostname or '')))
                evidence=dict(text=raw,coordinates=[coord(page_no,block[:4])],source='original_pdf_text_block',target_phrase=phrase)
                identity=dict(organization_id=ALIASES['organization_id'],canonical_name=ALIASES['canonical_name'],matched_alias_raw=hit.group(),alias_rules_version=ALIASES['version'],evidence=['explicit_target_data_use_in_original_pdf'],year_label_from_raw=None,mixed_reference=False,identity_status='candidate_unverified',resource_type='explicit_data_source_attribution')
                reference=dict(id=ident,reference_id=uid('ref',ident),raw_citation=raw,title=None,authors=[],year=None,coordinates=[],organization_candidate=identity,source='original_pdf_explicit_attribution',source_urls=urls,attribution_evidence=evidence)
                index['references'].append(reference)
                pid=uid('attribution_context',ident)
                index['contexts'].append(dict(id=pid,text=raw,kind='p',section_id=None,coordinates=evidence['coordinates'],sentences=[],previous_paragraph_id=None,next_paragraph_id=None,source='original_pdf_text_block'))
                o=dict(location_id=uid('loc',ident),raw_marker='',marker_source='original_pdf_explicit_source_use',citation_form='explicit_source_use_without_marker',paragraph_id=pid,offsets=dict(start=None,end=None,unit='unicode_codepoint',end_exclusive=True),coordinates=evidence['coordinates'],source_evidence_ids=[ident],links=[],human_review_status='not_reviewed',style='attribution',typography='not_applicable',carrier='p',expanded_numbers=[],unresolved_numbers=[])
                add_edge(index,o,reference,'explicit_data_use_in_original_pdf');o['links'][0]['link_status']='explicit_source_attribution';index['occurrences'].append(o)
                changes.append(dict(kind='recover_explicit_source_use',location_id=o['location_id'],reference_id=reference['reference_id'],evidence=evidence))
    return changes
