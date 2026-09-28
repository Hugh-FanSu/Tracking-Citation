import copy
import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from paper_citation_pipeline.local_review import (Reviewer, review_references,
    validate_references, validate_context, gate, source_lines)
from paper_citation_pipeline.delivery import compact, decode, seal, blockers, prepare_delivery


class LocalReviewTests(unittest.TestCase):
    def decision(self, ident='r'):
        return dict(id=ident, role='author', boundary='clean', evidence='UNEP and AMAP',
                    author_names=['UNEP', 'AMAP'], title='Mercury report 2018', year='2019', reason='signature')

    def test_reviews_all_references_even_unflagged_and_joint(self):
        refs=[dict(reference_id='r', raw_citation='UNEP and AMAP (2019). Mercury report 2018.', organization_candidate=None),
              dict(reference_id='r2', raw_citation='UNEP and AMAP (2019). Mercury report 2018.', organization_candidate={'joint_authorship':{'coauthors':['wrong']}})]
        target=dict(organization_id='UNEP',canonical_name='UNEP',version='1')
        with tempfile.TemporaryDirectory() as temp, patch('paper_citation_pipeline.local_review.config',return_value={'model':'test','max_tokens':8192}), patch('paper_citation_pipeline.local_review.Client') as client:
            client.return_value.request.return_value=({'references':[self.decision(),self.decision('r2')]},{'usage':{'total_tokens':40}})
            reviewer=Reviewer('config',temp)
            result=review_references({'references':refs},target,reviewer)
            self.assertEqual(result['reviewed'],2)
            self.assertEqual(refs[0]['year'],'2019')
            self.assertEqual(refs[1]['organization_candidate']['joint_authorship']['coauthors'],['UNEP','AMAP'])
            review_references({'references':refs},target,Reviewer('config',temp))
            self.assertEqual(client.return_value.request.call_count,1)

    def test_missing_entry_and_hallucinated_evidence_rejected(self):
        batch=[{'id':'r','raw':'UNEP and AMAP (2019). Mercury report 2018.'}]
        with self.assertRaises(ValueError):validate_references({'references':[]},batch)
        d=self.decision();d['title']='invented title'
        with self.assertRaises(ValueError):validate_references({'references':[d]},batch)

    def test_context_spans_support_cross_page_but_not_unchecked_block_join(self):
        lines=[dict(id='a',page=1,block_id=0,text='The report (UNEP, 2019) says'),
               dict(id='b',page=2,block_id=0,text='emissions must fall.')]
        d=dict(status='complete',relevant=True,segments=[dict(start_line='a',end_line='b',start=0,end=20)])
        with self.assertRaises(ValueError):validate_context(d,lines,'(UNEP, 2019)')
        d['segments']=[dict(start_line=l['id'],end_line=l['id'],start=0,end=len(l['text'])) for l in lines]
        self.assertEqual(validate_context(d,lines,'(UNEP, 2019)'),lines[0]['text']+'\n'+lines[1]['text'])
        d['segments']=d['segments'][1:]
        with self.assertRaises(ValueError):validate_context(d,lines,'(UNEP, 2019)')

    def test_api_failure_cached_and_never_auto_retried(self):
        with tempfile.TemporaryDirectory() as temp, patch('paper_citation_pipeline.local_review.config',return_value={'model':'test','max_tokens':8192}), patch('paper_citation_pipeline.local_review.Client') as client:
            client.return_value.key='secret'
            client.return_value.request.side_effect=ValueError('secret timeout')
            one=Reviewer('config',temp).request('x','prompt',{'x':1},lambda x:None)
            two=Reviewer('config',temp).request('x','prompt',{'x':1},lambda x:None)
            self.assertEqual(one['status'],'failed');self.assertNotIn('secret',one['error'])
            self.assertEqual(client.return_value.request.call_count,1)
            self.assertEqual(two['status'],'failed')

    def packet(self):
        p=dict(paper_id='p',page_count=1,source={'pdf':'/local/private/p.pdf','sha256':'a'*64},target={'canonical_name':'UNEP'},
            metadata={'title':'Paper'},citation_index={'references':[],'contexts':[],'occurrences':[]},
            target_candidates=[],pdf_pages=[{'page':1,'text':'Long text '*100,'lines':[{'text':'Long text '*100,'bbox':[0,0,10,10]}]}],
            quality={'validation_errors':[]},unresolved={},parser_result={'docling':{'document':{'tables':[{'data':{'table_cells':[{'text':'table content'}]}}]}}})
        p['mention_review']={'status':'completed','decisions':{}}
        p['metadata_review']={'status':'completed','result':{'status':'complete'}}
        p['local_verification']=gate(p,{'status':'completed','decisions':{}},{'status':'completed'}, {})
        seal(p)
        return p

    def test_missing_model_and_unresolved_are_never_passed(self):
        p=self.packet()
        result=gate(p,{'status':'pending'},{'status':'pending'}, {})
        self.assertFalse(result['upload_eligible'])
        p['unresolved']={'source_conflicts':[{'id':'1'}]}
        self.assertIn('local_unresolved_source_conflicts',blockers(p))
        self.assertIn('verification_stale_or_missing',blockers(p))

    def test_cloud_roundtrip_without_any_source_files_and_tampering_detected(self):
        p=self.packet();a=compact(p)
        self.assertEqual(len(a['text_pool']),1)
        decoded=decode(json.loads(gzip.decompress(gzip.compress(json.dumps(a).encode()))))
        self.assertEqual(decoded['pdf_pages'],p['pdf_pages'])
        self.assertEqual(decoded['document_structure']['tables'][0]['data']['table_cells'][0]['text'],'table content')
        self.assertNotIn('/local/private',json.dumps(a))
        a['text_pool'][0]='corrupted'
        with self.assertRaises(ValueError):decode(a)

    def test_seal_invalidates_changed_context_or_review(self):
        p=self.packet();self.assertEqual(blockers(p),[])
        p['pdf_pages'][0]['text']='changed'
        self.assertIn('verification_stale_or_missing',blockers(p))
        p=self.packet();p['local_verification']['accuracy_95_certified']=True
        self.assertIn('verification_record_changed',blockers(p))

    def test_no_workbook_means_no_upload_zip(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'p.json';path.write_text(json.dumps(self.packet()))
            report=prepare_delivery(temp,[path])
            self.assertEqual(report['status'],'blocked')
            self.assertIn('completed_workbook_required',report['blockers'])
            self.assertEqual(list(Path(temp).glob('*.zip')),[])

    def test_completed_delivery_contains_no_pdf_and_detects_stale_excel(self):
        import zipfile
        from paper_citation_pipeline.excel import export_packets
        from paper_citation_pipeline.numbering import initialize, assign
        from openpyxl import Workbook
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);state=root/'state.json';initialize(state,0,0)
            p=self.packet();p['citation_index']['sections']=[];p['quality']['readiness']='ready_for_annotation'
            p['metadata']['authors']=[];p['metadata']['abstract']='Abstract'
            assign(p,state);seal(p)
            packet=root/'p.json';packet.write_text(json.dumps(p))
            wb=Workbook();wb.active.title='Papers';wb.active.append(['ID','Title'])
            template=root/'blank.xlsx';wb.save(template)
            mapping=root/'mapping.json';mapping.write_text(json.dumps({'sheets':[{'sheet':'Papers','entity':'papers','columns':{'ID':'paper_id','Title':'title'}}]}))
            xlsx=root/'citations.xlsx';export_packets([packet],template,mapping,xlsx,id_state=state)
            result=prepare_delivery(root,[packet],xlsx)
            self.assertEqual(result['status'],'ready',result)
            with zipfile.ZipFile(result['package']) as z:
                self.assertFalse(any(n.lower().endswith('.pdf') for n in z.namelist()))
                name=next(n for n in z.namelist() if n.endswith('.json.gz'))
                restored=decode(json.loads(gzip.decompress(z.read(name))))
                self.assertEqual(restored['metadata']['title'],'Paper')
            p['metadata']['title']='changed';seal(p);packet.write_text(json.dumps(p))
            result=prepare_delivery(root,[packet],xlsx)
            self.assertEqual(result['status'],'blocked')
            self.assertIsNone(result['package'])
            self.assertIn('workbook_source_packets_mismatch',result['blockers'])

    def test_caption_prefix_can_only_be_trimmed_with_exact_evidence(self):
        raw='Caption text. IUCN and UNEP, 2013. The World Database on Protected Areas.'
        clean=raw[len('Caption text. '):]
        d=dict(id='r',role='author',boundary='clean',reference_text=clean,evidence='IUCN and UNEP',
               author_names=['IUCN','UNEP'],title='The World Database on Protected Areas',year='2013',reason='author signature')
        validate_references({'references':[d]},[{'id':'r','raw':raw}])
        d['reference_text']='IUCN and UNEP, 2013. An invented replacement.'
        with self.assertRaises(ValueError):validate_references({'references':[d]},[{'id':'r','raw':raw}])

    def test_invalid_cloud_text_index_and_duplicate_mention_gates(self):
        p=self.packet();a=compact(p);a['payload']['metadata']['title']={'$text':99999}
        with self.assertRaises(ValueError):decode(a)
        p['mention_review']={'status':'completed','decisions':{'m':{'kind':'source_use','linked_record_ids':[]}}}
        checked=gate(p,{'status':'completed','decisions':{}},{'status':'completed'}, {})
        self.assertIn('target_mention_without_resolved_citation',[b['code'] for b in checked['blockers']])

    def test_generic_personal_authors_cannot_be_promoted_to_target_organization(self):
        d=dict(id='r',role='author',boundary='clean',evidence='Smith J',author_names=['Smith J'],title='Study',year='2020',reason='has authors')
        with self.assertRaisesRegex(ValueError,'Target organization absent'):
            validate_references({'references':[d]},[{'id':'r','raw':'Smith J (2020). Study.'}],{'canonical_name':'United Nations Environment Programme','aliases':[{'name':'UNEP'}]})

    def test_completed_usage_releases_unused_output_reservation(self):
        with tempfile.TemporaryDirectory() as temp, patch('paper_citation_pipeline.local_review.config',return_value={'model':'test','max_tokens':8192}), patch('paper_citation_pipeline.local_review.Client') as client:
            client.return_value.request.return_value=({'ok':True},{'usage':{'completion_tokens':20}})
            r=Reviewer('cfg',temp)
            r.request('reference_regions','prompt',{'x':1},lambda x:None)
            self.assertEqual(r.output_tokens_reserved,20)

    def test_complete_raw_signature_survives_incomplete_model_author_list(self):
        raw='UNEP and AMAP (2019). Mercury report 2018.'
        ref=dict(reference_id='r',raw_citation=raw,organization_candidate=None)
        decision=self.decision();decision['author_names']=['UNEP']
        with tempfile.TemporaryDirectory() as temp, patch('paper_citation_pipeline.local_review.config',return_value={'model':'test','max_tokens':8192}), patch('paper_citation_pipeline.local_review.Client') as client:
            client.return_value.request.return_value=({'references':[decision]},{})
            review_references({'references':[ref]},dict(organization_id='UNEP',canonical_name='UNEP'),Reviewer('cfg',temp))
            self.assertEqual(ref['verified_author_signature']['text'],'UNEP and AMAP')
            self.assertEqual(ref['organization_candidate']['joint_authorship']['raw_author_label'],'UNEP and AMAP')

    def test_context_rejects_word_cut_and_preserves_existing_paragraph(self):
        lines=[dict(id='a',page=1,block_id=0,text='UNEP reports decarbonization.'),dict(id='b',page=2,block_id=1,text='The paragraph continues here.')]
        d=dict(status='complete',relevant=True,segments=[dict(start_line='a',end_line='a',start=0,end=21)])
        with self.assertRaisesRegex(ValueError,'cuts through a word'):
            validate_context(d,lines,'UNEP')
        d['segments']=[dict(start_line='a',end_line='a',end=None)]
        self.assertEqual(validate_context(d,lines,'UNEP'),lines[0]['text'])
        with self.assertRaisesRegex(ValueError,'omit existing'):
            validate_context(d,lines,'UNEP',' '.join(l['text'] for l in lines))
        d['segments'].append(dict(start_line='b',end_line='b',end=None))
        self.assertIn('continues here.',validate_context(d,lines,'UNEP',' '.join(l['text'] for l in lines)))
