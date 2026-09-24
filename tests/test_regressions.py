import copy
from pathlib import Path
import tempfile
import unittest
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
import pymupdf
from standardize_citations import normalize,unep_rows,org_reference
from reference_repairs import repair
from source_checks import source_conflicts
from test_standardize import sample,ref

class RegressionTests(unittest.TestCase):
    def test_title_year_does_not_mean_merged_entry(self):
        b=ref('b0','UNEP, 2019. Global Mercury Assessment 2018. United Nations Environment Programme.','2018')
        result=org_reference(b)
        self.assertFalse(result['mixed_reference'])
        self.assertEqual(result['year_label_from_raw'],'2019')
        self.assertEqual(result['bibliographic_date_disagreement']['reason'],'parser_year_occurs_in_title')
        bad=ref('b1','UNEP, 2019. Assessment. Smith, 2012. Other article.','2012')
        self.assertTrue(org_reference(bad)['mixed_reference'])

    def test_joint_author_and_title_first_publisher(self):
        for text in ['IEA & UNEP, 2023. Buildings report.', 'Global cooling watch 2023. United Nations Environment Programme; 2023.']:
            self.assertIsNotNone(org_reference(ref('b0',text,'2023')))
        self.assertIsNone(org_reference(ref('b0','Smith, 2023. Research about UNEP. Journal.','2023')))

    def test_no_comma_parenthetical_not_prose(self):
        refs=[ref('b0','UNEP, 2020. Guidelines.','2020')]
        self.assertEqual(len(unep_rows(normalize(sample('(UNEP 2020)',refs),'p'))),1)
        self.assertEqual(len(unep_rows(normalize(sample('UNEP 2020 Report [22]',refs),'p'))),0)

    def test_no_date_not_retrieval_year(self):
        b=ref('b0','UNEP. (n.d.). Cities and climate change. Retrieved November 17, 2024.','2024')
        self.assertEqual(org_reference(b)['year_label_from_raw'],'n.d.')
        self.assertFalse(org_reference(b)['mixed_reference'])
        self.assertEqual(len(unep_rows(normalize(sample('(UNEP, n.d.)',[b]),'p'))),1)

    def test_nested_alias_and_inherited_year(self):
        refs=[ref('b0','United Nations Environmental Program (UNEP), 2011. Report.','2011'),
              ref('b1','UNEP/SETAC Life Cycle Initiative, 2013. Methods.','2013'),
              ref('b2','United Nations Environmental Program (UNEP), 2020. Guidelines.','2020')]
        rows=unep_rows(normalize(sample('(United Nations Environmental Program (UNEP), 2011; UNEP/SETAC Life Cycle Initiative, 2013; 2020)',refs),'p'))
        self.assertEqual(len(rows),3)
        self.assertEqual(len({r['location_id'] for r in rows}),1)
        self.assertEqual(rows[-1]['link_status'],'inferred_year_continuation')

    def test_source_glued_isbn_remains_blocked(self):
        raw='United Nations Environment Program (UNEP), 1998. Case Studies. ISBN 1-895720-29-XUNEP, (2019). Mineral resource governance.'
        self.assertTrue(org_reference(ref('b0',raw,'1998'))['mixed_reference'])

    def test_empty_tei_not_a_citation_location(self):
        m={'id':'c1','paragraph_id':'p1','raw_marker':'','offsets':{'start':3,'end':3},'style':'unknown','links':[]}
        index=normalize(sample('abc',[],[m]),'p')
        self.assertEqual(index['occurrences'],[])
        self.assertEqual(index['rejected_parser_mentions'][0]['original_mention'],m)

    def test_source_conflict_preserves_numeric_edge(self):
        index={'references':[{'reference_id':'report31','title':'Integrated Environmental Assessment Guidelines','organization_candidate':True}],
               'contexts':[{'id':'p1','text':'Use UNEP Integrated Environmental Assessment Guidelines [29].'}],
               'occurrences':[{'location_id':'loc1','paragraph_id':'p1','offsets':{'start':55,'end':59},'coordinates':[],
                               'links':[{'reference_id':'other29'}]}]}
        start=index['contexts'][0]['text'].index('[29]')
        index['occurrences'][0]['offsets']={'start':start,'end':start+4}
        original=copy.deepcopy(index)
        conflicts=source_conflicts(index)
        self.assertEqual(len(conflicts),1)
        self.assertEqual(conflicts[0]['numeric_linked_reference_ids'],['other29'])
        self.assertEqual(index,original)

    def test_pdf_two_single_line_references_split_with_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'sample.pdf';doc=pymupdf.open();page=doc.new_page()
            lines=['UNEP, 2009. Marine Litter: A Global Challenge.', 'UNEP/MAP, 2015. Marine Litter Assessment.']
            for y,text in zip([100,115],lines):page.insert_text((50,y),text,fontsize=10)
            doc.save(path);doc.close()
            with pymupdf.open(path) as doc:
                coords=[]
                for block in doc[0].get_text('dict')['blocks']:
                    for line in block.get('lines',[]):
                        x,y,r,b=line['bbox'];coords.append({'page':1,'x':x,'y':y,'width':r-x,'height':b-y})
            b=ref('b0',' '.join(lines),'2009');b['coordinates']=coords
            d=sample('(UNEP, 2009; UNEP/MAP, 2015)',[b]);original=copy.deepcopy(d)
            working,changes=repair(path,d)
            self.assertEqual(d,original)
            self.assertEqual(len(changes),1)
            self.assertEqual(len(working['bibliography']),2)
            self.assertEqual(len(unep_rows(normalize(working,'p'))),2)
            self.assertEqual(changes[0]['source_sha256'],'test')

if __name__=='__main__':unittest.main()
