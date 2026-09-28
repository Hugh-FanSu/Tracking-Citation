"""Independent PDF author/year inventory; flags gaps, never invents citation edges."""
import re
from collections import Counter
from standardize_citations import ORG_YEAR,ORG,ALIASES
from context_repair import charmap,letters

def audit(pages,index,rows):
    findings=[];inventory=[]
    refs=[r for r in index['references'] if r.get('organization_candidate')]
    names={re.sub(r'\s+','',a['name']).casefold() for a in ALIASES['aliases']}
    short=[re.escape(a['name']) for a in ALIASES['aliases'] if 2<=len(a['name'])<=12 and '/' not in a['name']]
    joint=re.compile(r'(?<!\w)(?:'+('|'.join(short) or r'(?!)')+r')\s*/\s*[A-Za-z][A-Za-z0-9-]{1,30}\b',re.I)
    unknown={}
    for page in pages:
        text=re.sub(r'\u00ad\s*','',page['text'])
        normalized,positions=charmap(text);excluded=[]
        for r in refs:
            if page['page'] not in {c['page'] for c in r.get('coordinates',[])}:continue
            raw=charmap(r.get('raw_citation',''))[0];needle=raw[:140]
            if len(needle)<25:continue
            start=normalized.find(needle)
            if start>=0:
                end=min(len(positions)-1,start+len(raw)-1)
                excluded.append((positions[start],positions[end]+1))
        for hit in joint.finditer(text):
            classified=any(r.get('source')=='original_pdf_table_document_identifier' and re.sub(r'\s+','',r.get('raw_citation','')).casefold().startswith(re.sub(r'\s+','',hit.group()).casefold()+'/') and page['page'] in {c['page'] for c in r.get('coordinates',[])} for r in refs)
            signed=any(re.sub(r'\s+','',hit.group()).casefold() in re.sub(r'\s+','',(r.get('organization_candidate',{}).get('joint_authorship') or {}).get('raw_author_label','')).casefold() for r in refs if isinstance(r.get('organization_candidate'),dict))
            if classified or signed:continue
            if re.sub(r'\s+','',hit.group()).casefold() not in names:
                unknown.setdefault(hit.group(),set()).add(page['page'])
        for match in ORG_YEAR.finditer(text):
            if any(a<=match.start()<b for a,b in excluded):continue
            inventory.append({'page':page['page'],'marker':match.group(),'year':re.sub(r'\s+','',match.group(2).lower())})
    for name,where in unknown.items():
        findings.append({'code':'unknown_joint_author','marker':name,'pages':sorted(where),
                         'reason':'PDF contains an unconfigured compound author label; inspect local aliases, do not assume target identity'})
    for r in refs:
        if not isinstance(r.get('organization_candidate'),dict) or 'reference_id' not in r:continue
        if r.get('organization_candidate',{}).get('identity_status')=='candidate_related_organization_scope':
            findings.append({'code':'related_organization_scope_unconfirmed','reference_id':r['reference_id'],
                             'raw_reference':r.get('raw_citation'),'reason':'Compound author label shares configured prefix; inclusion scope is not confirmed'})
        linked=[o for o in index.get('occurrences',[]) if any(l['reference_id']==r['reference_id'] for l in o['links'])]
        if not linked:
            findings.append({'code':'target_reference_without_body_link','reference_id':r['reference_id'],
                             'reason':'Target reference exists but has no linked occurrence; bibliography-only or missed citation requires distinction'})
    # A third-party title about the target is not proof of target authorship.
    # Keep its linked occurrences visible for possible secondary-source use.
    for r in index['references']:
        if r.get('target_identity_excluded_due_to_verified_subentry'):continue
        if r.get('organization_candidate') or not re.search(r'(?<!\w)(?:'+ORG+r')(?!\w)',r.get('title') or '',re.I):continue
        linked=[o for o in index.get('occurrences',[]) if any(l['reference_id']==r['reference_id'] for l in o['links'])]
        # GROBID can retain the marker but omit its edge. Record a possible
        # local author/year match for audit only; do not manufacture an edge.
        family=(r.get('authors') or [{}])[0].get('family') or ''
        year=str(r.get('year_label') or r.get('year') or '')
        possible=[]
        if family and year:
            pattern=re.compile(r'(?<!\w)'+re.escape(family)+r'\s*,?\s*'+re.escape(year)+r'(?!\w)',re.I)
            possible=[o for o in index.get('occurrences',[]) if not o['links'] and pattern.search(o['raw_marker'])]
        if linked or possible:
            findings.append(dict(code='target_named_in_third_party_source',reference_id=r['reference_id'],
                raw_reference=r.get('raw_citation'),location_ids=[o['location_id'] for o in linked],
                markers=[o['raw_marker'] for o in linked],
                possible_unlinked_locations=[{'location_id':o['location_id'],'marker':o['raw_marker'],
                    'paragraph_id':o.get('paragraph_id'),'coordinates':o.get('coordinates',[])} for o in possible],
                reason='Target appears in a third-party source title; possible indirect use requires classification, not target authorship'))
    counts=Counter((x['page'],x['year']) for x in inventory)
    for (page,year),count in counts.items():
        linked={r['location_id'] for r in rows if r.get('year_label_from_raw')==year and page in r.get('pdf_pages',[])}
        if len(linked)<count:findings.append({'code':'pdf_author_year_not_fully_linked','page':page,'year':year,'pdf_markers':count,'linked_locations':len(linked)})
    return {'scope':'PDF author-year markers and compound aliases; numeric recall and semantic attribution not certified',
            'status':'needs_attention' if findings else 'no_gap_detected','inventory':inventory,'findings':findings}
