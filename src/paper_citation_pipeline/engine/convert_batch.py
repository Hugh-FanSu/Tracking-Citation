"""Original PDF -> GROBID/Docling -> per-paper evidence packet and reading MD."""
import argparse
import os
import hashlib
import json
import logging
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'runtime'))
sys.path.insert(0,str(HERE.parents[1]))
from paper_citation_pipeline.progress import Progress
from paper_citation_pipeline.numbering import assign, check
from standardize_citations import normalize, unep_rows, ORG, uid, ALIASES, ALIAS_PATH
from match_report_catalog import match_reference
from validate_packet import validate
from reference_repairs import repair
from source_checks import source_conflicts


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path,data):
    tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    tmp.replace(path)


def packet(path, parser_dir, output, catalog=None, expect_target=False, id_state=None):
    import pymupdf
    from lxml import etree
    data=json.loads(path.read_text())
    if 'source' not in data:raise ValueError('Parser output has no source or structure')
    pdf=Path(data['source']['pdf'])
    if digest(pdf)!=data['source']['sha256']:raise ValueError('Original PDF hash differs from parser input')
    artifacts={}
    for folder,suffix in [('tei','.tei.xml'),('docling','.docling.json'),('md','.md')]:
        src=parser_dir/folder/(path.stem+suffix)
        if src.exists():
            dst=output/folder/src.name
            if src.resolve()!=dst.resolve():shutil.copy2(src,dst)
            artifacts[folder]={'path':str(dst),'sha256':digest(dst)}
    sentences=set()
    if 'tei' in artifacts:
        tree=etree.parse(artifacts['tei']['path'],etree.XMLParser(resolve_entities=False,no_network=True))
        sentences={''.join(s.itertext()) for s in tree.findall('.//{http://www.tei-c.org/ns/1.0}s')} - {''}
    working,corrections=repair(pdf,data)
    from bracket_ranges import recover as restore_bracket_ranges
    corrections.extend(restore_bracket_ranges(pdf,working))
    from superscript_groups import recover as restore_superscript_groups
    working.setdefault('pdf_citation_groups',[]).extend(restore_superscript_groups(pdf,working))
    idx=normalize(working,path.stem,sorted(sentences))
    from metadata_repair import repair_metadata
    metadata,metadata_changes=repair_metadata(pdf,data)
    corrections.extend(metadata_changes)
    from paper_citation_pipeline.author_review import review_authors
    author_findings=review_authors(idx,os.environ.get("PAPER_CITATION_AUTHOR_API_CONFIG"),output)
    from target_recovery import recover as recover_citations
    citation_changes,citation_findings=recover_citations(pdf,working,idx)
    from footnote_sources import recover as recover_footnotes
    footnote_changes,footnote_findings=recover_footnotes(pdf,idx)
    citation_changes.extend(footnote_changes);citation_findings.extend(footnote_findings)
    from explicit_attribution import recover as recover_attributions
    citation_changes.extend(recover_attributions(pdf,idx))
    from local_sources import recover_local_sources
    local_changes,local_findings=recover_local_sources(pdf,idx)
    citation_changes.extend(local_changes);citation_findings.extend(local_findings)
    citation_findings.extend(author_findings)
    corrections.extend(citation_changes)
    pages=[]
    with pymupdf.open(pdf) as doc:
        for n,page in enumerate(doc,1):
            lines=[]
            for block in page.get_text('dict')['blocks']:
                for line in block.get('lines',[]):
                    lines.append({'text':''.join(s['text'] for s in line['spans']), 'bbox':list(line['bbox'])})
            pages.append({'page':n,'width':page.rect.width,'height':page.rect.height,
                          'text':page.get_text(), 'lines':lines,'origin':'top-left','unit':'PDF point',
                          'source':'original_pdf_text_layer'})
    attributions=[]
    pattern=re.compile(r'(?<!\w)('+ORG+r')(?!\w)',re.I)
    for p in idx['contexts']:
        for hit in pattern.finditer(p['text']):
            attributions.append({'id':uid('attribution',idx['document_id'],p['id'],hit.span()),
                                 'paragraph_id':p['id'],'start':hit.start(),'end':hit.end(),'raw_alias':hit.group(),
                                 'status':'unclassified_organization_mention_or_attribution','coordinates':p.get('coordinates',[])})
    pdf_mentions=[]
    for page in pages:
        for hit in pattern.finditer(page['text']):
            pdf_mentions.append({'page':page['page'],'start':hit.start(),'end':hit.end(),'raw_alias':hit.group(),
                                 'context':page['text'][max(0,hit.start()-220):hit.end()+320],
                                 'classification':'unclassified_pdf_mention','source':'original_pdf_text_layer'})
    from marker_evidence import locate,repair_nested_author_marker
    corrections.extend(repair_nested_author_marker(pdf,idx))
    corrections.extend(locate(pdf,idx))
    candidates=unep_rows(idx)
    from context_repair import repair_contexts
    context_changes=repair_contexts(pdf,idx,candidates,data.get('docling',{}).get('document',{}))
    corrections.extend(context_changes)
    for row in candidates:
        row['inclusion_status']='pending_annotation'
        row['resource_type_excludes_collection']=False
        row['report_match_required_for_inclusion']=False
        if row.get('citation_form')=='explicit_source_use_without_marker':
            row['report_match']={'status':'unmatched','matched_title':None,'reason':'data_source_attribution_not_a_verified_report_title'}
        elif (row.get('attribution_evidence') or {}).get('pointer_status')=='unresolved_or_conflicting_number':
            row['report_match']={'status':'unmatched','matched_title':None,'reason':'original_footnote_cross_reference_unresolved'}
        elif row['report_identity_status']=='candidate_related_organization_scope':
            row['report_match']={'status':'scope_review_required','matched_title':None,'reason':'compound_author_scope_not_confirmed'}
        elif row['report_identity_status']=='blocked_mixed_reference':
            row['report_match']={'status':'blocked_reference','matched_title':None,'reason':'mixed_reference'}
        elif catalog is None:
            row['report_match']={'status':'not_searched','matched_title':None,'reason':'no_catalog_supplied'}
        else:
            temporary={**row,'pdf_review':{'reference_text_after_review':row['raw_reference'],
                       'reference_correction_status':'original_entry_retained'}}
            match=match_reference(temporary,catalog['rows'])
            match['status']={'已匹配':'matched','未匹配':'unmatched','待核实':'ambiguous'}[match['status']]
            if match.get('catalog_resource_id'):
                match['catalog_resource_id']=ALIASES['organization_id']+'-resource-'+match['catalog_resource_id'].split('-resource-',1)[-1]
            row['report_match']=dict(match,catalog_source=catalog.get('source'),catalog_sheet=catalog.get('sheet'))
    from recall_audit import audit as recall_audit
    recall=recall_audit(pages,idx,candidates)
    recall['findings'].extend(citation_findings)
    if recall['findings']:recall['status']='needs_attention'
    unresolved={'recall_audit_findings':recall['findings'],'rejected_parser_mentions':idx['rejected_parser_mentions'],'source_consistency_conflicts':source_conflicts(idx),'index_issues':idx['review_queue'],
                'unlinked_organization_year':idx['organization_unlinked_candidates'],
                'unresolved_reference_region_entries':[e for e in working.get('reference_region_audit',{}).get('entries',[]) if e['status']=='unresolved'],
                'numeric_pdf_candidates':data.get('unlinked_numeric_pdf_groups',[]),
                'superscript_candidates':data.get('unlinked_superscript_candidates',[]),
                'possible_merged_reference_ids':data.get('quality',{}).get('possible_merged_bibliography_ids',[])}
    issues=list(data.get('quality',{}).get('warnings',[]))
    if expect_target and not candidates:
        issues.append('EXPECTED_TARGET_NO_LINKED_HIT: investigate aliases, bibliography-only evidence and missing markers; do not manufacture a hit')
    if corrections:issues.append(f'PDF-evidenced bibliography repairs: {len(corrections)}; original parser retained')
    issues.extend(f'{k}: {len(v)}' for k,v in unresolved.items() if v)
    if any(not p['text'].strip() for p in pages):issues.append('Some pages have no original PDF text layer; inspect OCR/page coverage')
    if data.get('docling',{}).get('page_count')!=len(pages):issues.append('Docling/source page count mismatch')
    if any(not r['citation_sentence'] for r in candidates):issues.append('Some target candidates lack exact TEI sentence')
    if any(not r['coordinates'] for r in candidates):issues.append('Some target candidates lack marker-level coordinates')
    if attributions:issues.append('Organization mention/attribution candidates require per-paper annotation')
    if any(r['report_match']['status'] in {'blocked_reference','ambiguous'} for r in candidates):issues.append('Some report-name matches remain unresolved')
    result={'packet_schema':'paper-citation-packet/1.0','paper_id':path.stem,'document_id':idx['document_id'],
            'source':data['source'],'page_count':len(pages),'target':ALIASES,
            'metadata':metadata,
            'parser_result':data,'citation_index':idx,'pdf_pages':pages,'target_candidates':candidates,
            'organization_attributions':attributions,'unresolved':unresolved,
            'corrections':corrections,'target_pdf_mentions':pdf_mentions,
            'reference_region_audit':working.get('reference_region_audit',{}),
            'recall_audit':recall,
            'target_coverage':{'expected_target':expect_target,'linked_candidate_count':len(candidates),
                               'pdf_mention_count':len(pdf_mentions),'text_attribution_count':len(attributions),
                               'status':'linked_candidates_found' if candidates else 'no_linked_candidates'},
            'quality':{'readiness':'pending_validation','issues':issues,'recall_certified':False,
                       'paragraph_boundaries_certified':False},
            'provenance':{'skill_version':'1.1.1','tool_version':'0.8.4','artifacts':artifacts,
                          'parser_output_sha256':digest(path),
                          'script_hashes':{str(p.relative_to(HERE)):digest(p) for p in HERE.rglob('*.py')},
                          'alias_config_sha256':digest(ALIAS_PATH),
                          'catalog':None if catalog is None else {k:catalog.get(k) for k in ('source','sheet','snapshot_sha256')}}}
    errors=validate(result)
    if data.get('status')!='success':errors.append('Parser stages not fully successful')
    if not {'tei','docling','md'}<=artifacts.keys():errors.append('Required raw/reading artifacts missing')
    result['quality']['validation_errors']=errors
    result['quality']['readiness']='failed' if errors else ('ready_with_issues' if issues else 'ready_for_annotation')
    if not errors and id_state is not None:assign(result,id_state)
    save(output/'json'/path.name,result)
    return {'paper':path.stem,'source_pdf':str(pdf),'source_sha256':data['source']['sha256'],
            'page_count':len(pages),'readiness':result['quality']['readiness'],
            'target_candidates':len(candidates),'pdf_target_mentions':len(pdf_mentions),'reference_repairs':len(corrections),
            'validation_errors':errors,'issue_count':len(issues)}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input',type=Path)
    ap.add_argument('--parser-output',type=Path)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--id-state',type=Path,required=True)
    ap.add_argument('--catalog-json',type=Path)
    ap.add_argument('--resume',action='store_true')
    ap.add_argument('--expect-target',action='store_true',help='Flag papers with no linked target hit; never assume their links exist')
    ap.add_argument('--ocr',action='store_true')
    ap.add_argument('--grobid-url',default='http://localhost:8070')
    ap.add_argument('--stream-export',type=Path)
    args=ap.parse_args()
    check(args.id_state)
    out=args.output.resolve()
    for f in ['tei','docling','md','json','logs']:(out/f).mkdir(parents=True,exist_ok=True)
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s',handlers=[logging.StreamHandler(),logging.FileHandler(out/'logs/packet.log')])
    parser_dir=args.parser_output.resolve() if args.parser_output else out/'_parser'
    if parser_dir==out:ap.error('--output must differ from existing --parser-output to preserve raw JSON')
    if args.parser_output is None:
        if args.input is None:ap.error('--input or --parser-output required')
        from types import SimpleNamespace
        from pipeline import process_pdf
        from docling_worker import Worker
        import atexit
        worker=Worker(args.ocr);atexit.register(worker.close)
        engine_args=SimpleNamespace(output=parser_dir,logs=out/'logs',grobid_url=args.grobid_url,
                                    grobid_timeout=600,docling_timeout=1800,retries=2,ocr=args.ocr,
                                    resume=args.resume,docling_worker=worker)
        for folder in ['tei','json','md','docling']:(parser_dir/folder).mkdir(parents=True,exist_ok=True)
    catalog=None
    if args.catalog_json:
        catalog=json.loads(args.catalog_json.read_text())
        catalog['snapshot_sha256']=digest(args.catalog_json)
    reports=[]
    engine_reports=[]
    if args.parser_output is None:
        pdfs=sorted(p for p in args.input.iterdir() if p.is_file() and p.suffix.lower()=='.pdf')
        paths=[parser_dir/'json'/(p.stem+'.json') for p in pdfs]
    else:
        paths=[p for p in sorted((parser_dir/'json').glob('*.json')) if not p.name.endswith('.stages.json')]
    progress=Progress('PDF → MD/JSON' if args.parser_output is None else '解析缓存 → MD/JSON',len(paths),out/'conversion-progress.json')
    save(out/'manifest.json',reports)
    exporter=None
    if args.stream_export:
        from paper_citation_pipeline.streaming import StreamingExport
        exporter=StreamingExport(json.loads(args.stream_export.read_text()),len(paths))
    for path in paths:
        start=time.perf_counter()
        try:
            if args.parser_output is None:
                engine_report=process_pdf(pdfs[len(reports)].resolve(),engine_args)
                engine_reports.append(engine_report)
                save(out/'engine-summary.json',engine_reports)
                if engine_report['status']!='success':raise ValueError('PDF engines failed; see logs')
            report=packet(path,parser_dir,out,catalog,args.expect_target,args.id_state)
        except Exception as exc:
            logging.exception('Failed to package %s',path.name)
            report={'paper':path.stem,'readiness':'failed','validation_errors':[str(exc)]}
            # Never leave an old successful packet under the same name after failure.
            save(out/'json'/path.name,{'packet_schema':'paper-citation-packet/1.0','paper_id':path.stem,'quality':report})
        report['processing_seconds']=round(time.perf_counter()-start,3)
        reports.append(report)
        logging.info('%s: %s',path.stem,report['readiness'])
        save(out/'manifest.json',reports)
        progress.advance(path.stem,report['readiness']=='failed')
        if exporter:
            try:exporter.advance(out/'json'/path.name,report['readiness']=='failed')
            except Exception:
                logging.exception('Excel checkpoint failed; parsing outputs retained')
    progress.finish()
    if args.parser_output is None:worker.close()
    if exporter:exporter.finish()
    return 0 if reports and all(r['readiness']!='failed' for r in reports) else 1


if __name__=='__main__':raise SystemExit(main())
