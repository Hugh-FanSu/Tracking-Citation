import copy
import json
from pathlib import Path
import tempfile
import unittest
import pymupdf
from test_standardize import sample,ref
from standardize_citations import normalize,unep_rows,org_reference
from target_recovery import recover_personal_authors,recover_numeric,recover_table_codes,recover_fragmented_table_sources,coord


class TargetRecoveryTests(unittest.TestCase):
    def personal(self,extra=False):
        b=ref('b0','de los Santos, C.B., Scott, A., 2020. Chapter. https://wedocs.unep.org/report','2020')
        b['authors']=[{'family':'De Los Santos','name':'C B De Los Santos'}]
        refs=[b]
        if extra:
            other=copy.deepcopy(b);other['id']='b1';other['raw_citation']='de los Santos, 2020. Different book.';refs.append(other)
        text='Benefits (de los Santos et al., 2020).';start=text.index('(')
        m=dict(id='m',paragraph_id='p1',raw_marker=text[start:-1],offsets=dict(start=start,end=len(text)-1),style='author_year',links=[])
        return normalize(sample(text,refs,[m]),'p')

    def test_personal_full_surname_recovered_once(self):
        idx=self.personal();self.assertEqual(len(recover_personal_authors(idx)),1)
        self.assertEqual(len(unep_rows(idx)),1);self.assertEqual(recover_personal_authors(idx),[])

    def test_same_author_year_ambiguity_not_resolved_by_target_only(self):
        idx=self.personal(True);self.assertEqual(recover_personal_authors(idx),[])
        self.assertEqual(unep_rows(idx),[])

    def test_related_label_is_scope_candidate_not_global_alias(self):
        value=org_reference(ref('b0','UNEP-OtherUnit, 2025. Protected areas.','2025'))
        self.assertEqual(value['identity_status'],'candidate_related_organization_scope')
        self.assertIn('compound_author_prefix_requires_scope_review',value['evidence'])

    def test_missing_numeric_range_uses_printed_labels_not_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'p.pdf';doc=pymupdf.open();page=doc.new_page()
            page.insert_text((50,100),'Important finding [1-3].')
            raws=['Smith, 2020. First unrelated resource.','UNEP, 2021. Long environmental report.','Jones, 2022. Third unrelated resource.']
            for n,raw in enumerate(raws,1):page.insert_text((50,200+n*25),f'[{n}] '+raw)
            doc.save(path);doc.close()
            idx=normalize(sample('Other text',[]),'p');refs=[]
            with pymupdf.open(path) as doc:
                page=doc[0]
                for n,raw in enumerate(raws,1):
                    b=ref(f'b{n}',raw,str(2019+n));b.update(reference_id=f'r{n}',coordinates=[coord(1,page.search_for(raw)[0])],organization_candidate=org_reference(b),order=99);refs.append(b)
                box=list(page.search_for('[1-3]')[0])
            idx['references']=refs
            data={'unlinked_numeric_pdf_groups':[dict(page=1,raw_marker='[1-3]',expanded_numbers=[1,2,3],bboxes=[box])]}
            changes,findings=recover_numeric(path,data,idx)
            self.assertEqual(len(changes),1);self.assertEqual(findings,[])
            self.assertEqual(len(unep_rows(idx)),1);self.assertEqual(len(idx['occurrences'][0]['links']),3)
            self.assertEqual(recover_numeric(path,data,idx)[0],[])
            refs[1]['coordinates']=[]
            other=normalize(sample('Other text',[]),'p');other['references']=refs
            self.assertEqual(recover_numeric(path,data,other)[0],[])

    def test_table_code_requires_original_pdf_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'p.pdf';doc=pymupdf.open();page=doc.new_page();page.insert_text((50,100),'UNEP/CMS/ScC16/Inf.9.1.');doc.save(path);doc.close()
            cell=dict(text='UNEP/CMS/ScC16/Inf.9.1.',bbox=dict(l=45,t=85,r=270,b=105,coord_origin='TOPLEFT'),start_row_offset_idx=0,end_row_offset_idx=1,start_col_offset_idx=0)
            data={'docling':{'document':{'tables':[dict(self_ref='#/tables/0',prov=[{'page_no':1}],data={'table_cells':[cell]})]}}}
            idx=normalize(sample('',[]),'p');self.assertEqual(len(recover_table_codes(path,data,idx)),1)
            self.assertEqual(unep_rows(idx)[0]['carrier'],'table')
            self.assertIsNone(unep_rows(idx)[0]['parsed_title_unverified'])
            cell['text']='UNEP/CMS/ScC17/Inf.9.1.'
            self.assertEqual(recover_table_codes(path,data,normalize(sample('',[]),'p')),[])

    def test_table_embedded_domain_links_not_administration_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'p.pdf';doc=pymupdf.open();page=doc.new_page(width=600,height=800)
            for x,text in [(40,'Reference'),(110,'Year'),(150,'Administration'),(225,'Link, description or')]:page.insert_text((x,80),text,fontsize=7)
            for y,title,year in [(120,'Seas programme','1974'),(180,'Other convention','1989')]:
                for x,text in [(40,title),(110,year),(150,'UNEP'),(225,'Source website')]:page.insert_text((x,y),text,fontsize=7)
            page.insert_link({'kind':pymupdf.LINK_URI,'from':pymupdf.Rect(225,113,280,121),'uri':'https://www.unep.org/seas'})
            doc.save(path);doc.close();idx=normalize(sample('',[]),'p')
            changes,pending=recover_fragmented_table_sources(path,idx)
            self.assertEqual(len(changes),1);self.assertEqual(len(pending),1)
            self.assertEqual(len(unep_rows(idx)),1)
            self.assertIsNone(unep_rows(idx)[0]['year_label_from_raw'])


class RecoveryAuditTests(unittest.TestCase):
    def test_document_code_classified_not_unknown_joint_author(self):
        from recall_audit import audit
        r=dict(reference_id='r',organization_candidate={'identity_status':'candidate_document_identifier'},raw_citation='UNEP/CMS/ScC16/Inf.9.1',coordinates=[{'page':1}],source='original_pdf_table_document_identifier')
        result=audit([{'page':1,'text':'UNEP/CMS/ScC16/Inf.9.1'}],{'references':[r],'occurrences':[{'links':[{'reference_id':'r'}]}]},[])
        self.assertEqual(result['findings'],[])

    def test_target_reference_without_link_warns_even_when_other_target_linked(self):
        from recall_audit import audit
        refs=[dict(reference_id=x,organization_candidate={'identity_status':'candidate_unverified'},raw_citation='UNEP, 2020. Report.',coordinates=[]) for x in ['a','b']]
        result=audit([],{'references':refs,'occurrences':[{'links':[{'reference_id':'a'}]}]},[])
        self.assertEqual(result['findings'][0]['code'],'target_reference_without_body_link')
        self.assertEqual(result['findings'][0]['reference_id'],'b')


class IncludedScopeTests(unittest.TestCase):
    def test_wcmc_explicitly_in_scope(self):
        identity=org_reference(ref('b0','UNEP-WCMC, 2025. Protected area profile.','2025'))
        self.assertEqual(identity['identity_status'],'candidate_unverified')
        self.assertEqual(identity['matched_alias_raw'],'UNEP')
        self.assertIn('target_in_joint_authorship',identity['evidence'])

class GeneralCoauthorTests(unittest.TestCase):
    def test_joint_author_labels_without_special_alias(self):
        for label in ['UNEP-WCMC','FAO/UNEP','IEA and UNEP','UNEP & IEA']:
            with self.subTest(label=label):
                identity=org_reference(ref('b',label+', 2025. Environmental report.','2025'))
                self.assertIsNotNone(identity['joint_authorship'])
                self.assertNotEqual(identity['identity_status'],'candidate_related_organization_scope')
    def test_title_or_funding_is_not_joint_author(self):
        from standardize_citations import joint_authorship
        for raw in ['A study of UNEP and IEA, 2025.', 'Funded by UNEP and IEA, 2025.']:
            self.assertIsNone(joint_authorship(ref('b',raw,'2025')))
