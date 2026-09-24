"""Structural acceptance only; never certifies semantic correctness or recall."""
import argparse
import hashlib
import json
from pathlib import Path


def validate(packet, verify_files=True):
    errors = []
    def require(condition, message):
        if not condition:
            errors.append(message)
    required = ['packet_schema','paper_id','document_id','source','page_count','metadata',
                'parser_result','citation_index','pdf_pages','target_candidates',
                'organization_attributions','unresolved','quality','provenance']
    missing = [x for x in required if x not in packet]
    if missing:
        return ['Missing fields: ' + ', '.join(missing)]
    require(packet['packet_schema']=='paper-citation-packet/1.0','Unsupported schema')
    require(packet['page_count'] > 0,'No pages')
    require([p['page'] for p in packet['pdf_pages']]==list(range(1,packet['page_count']+1)), 'PDF pages missing/duplicated')
    idx = packet['citation_index']
    refs = {r['reference_id'] for r in idx['references']}
    contexts = {p['id']:p for p in idx['contexts']}
    locations = {o['location_id'] for o in idx['occurrences']}
    require(len(refs)==len(idx['references']), 'Duplicate reference ID')
    require(len(contexts)==len(idx['contexts']), 'Duplicate context ID')
    require(len(locations)==len(idx['occurrences']), 'Duplicate location ID')
    edges = set()
    for o in idx['occurrences']:
        pid = o.get('paragraph_id')
        require(pid is None or pid in contexts, 'Dangling paragraph')
        if pid in contexts and o['offsets']['start'] is not None:
            a,b=o['offsets']['start'],o['offsets']['end']
            require(isinstance(b,int) and 0<=a<b<=len(contexts[pid]['text']), 'Invalid occurrence offsets')
            if o['marker_source'] in {'grobid_tei','grobid_tei_text_scan'}:
                require(contexts[pid]['text'][a:b]==o['raw_marker'],'Marker/offset mismatch')
        for c in o['coordinates']:
            require(1<=c['page']<=packet['page_count'],'Invalid marker page')
        for edge in o['links']:
            require(edge['reference_id'] in refs,'Dangling reference')
            require(edge['edge_id'] not in edges,'Duplicate edge ID')
            edges.add(edge['edge_id'])
    for row in packet['target_candidates']:
        require(row['location_id'] in locations,'Dangling candidate location')
        require(row['record_id'] in edges,'Dangling candidate edge')
        require(row['inclusion_status']=='pending_annotation','Converter must not pre-confirm candidate')
        require('status' in row.get('report_match',{}),'Missing independent report match status')
    for a in packet['organization_attributions']:
        p=contexts.get(a['paragraph_id'])
        require(p is not None,'Dangling attribution context')
        if p:
            require(p['text'][a['start']:a['end']]==a['raw_alias'],'Attribution offset mismatch')
    require(packet['quality']['recall_certified'] is False,'Cannot certify full recall')
    if packet['provenance'].get('skill_version','').startswith('1.1'):
        require(all(k in packet for k in ['corrections','target_pdf_mentions','target_coverage']), 'Missing 1.1 evidence fields')
        coverage=packet.get('target_coverage',{})
        require(coverage.get('linked_candidate_count')==len(packet['target_candidates']),'Target coverage count mismatch')
        pages={p['page']:p for p in packet['pdf_pages']}
        for hit in packet.get('target_pdf_mentions',[]):
            page=pages.get(hit['page'])
            require(page is not None,'Invalid PDF mention page')
            if page:require(page['text'][hit['start']:hit['end']]==hit['raw_alias'],'PDF mention offset mismatch')
        for conflict in packet['unresolved'].get('source_consistency_conflicts',[]):
            require(conflict['location_id'] in locations,'Dangling conflict location')
            require(conflict['title_suggested_reference_id'] in refs,'Dangling suggested reference')
        require(packet['parser_result']['source']['sha256']==packet['source']['sha256'],'Parser/source identity mismatch')
    if verify_files:
        path=Path(packet['source']['pdf'])
        require(path.exists(),'Source PDF unavailable')
        if path.exists():
            require(hashlib.sha256(path.read_bytes()).hexdigest()==packet['source']['sha256'],'PDF hash mismatch')
        for artifact in packet['provenance']['artifacts'].values():
            path=Path(artifact['path'])
            require(path.exists(),'Missing evidence artifact')
            if path.exists():require(hashlib.sha256(path.read_bytes()).hexdigest()==artifact['sha256'],'Evidence hash mismatch')
    return errors


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('path',type=Path)
    args=ap.parse_args()
    files=sorted(args.path.glob('*.json')) if args.path.is_dir() else [args.path]
    results=[]
    for path in files:
        try:errors=validate(json.loads(path.read_text()))
        except Exception as exc:errors=[str(exc)]
        results.append({'file':path.name,'passed':not errors,'errors':errors})
    print(json.dumps(results,ensure_ascii=False,indent=2))
    raise SystemExit(0 if results and all(r['passed'] for r in results) else 1)
