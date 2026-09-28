import json
from pathlib import Path
import sys
import tempfile
import unittest
import pymupdf

RUNTIME=Path(__file__).resolve().parents[1]/'src/paper_citation_pipeline/engine/runtime'
sys.path.insert(0,str(RUNTIME))
from semantic_recovery import recover


class NativeRecoveryTests(unittest.TestCase):
    def test_numeric_ranges_and_repeated_occurrences_without_parser_contexts(self):
        with tempfile.TemporaryDirectory() as temp:
            pdf=Path(temp)/'p.pdf';doc=pymupdf.open();page=doc.new_page()
            page.insert_text((40,60),'Used [15-17] and then [15-17].',fontsize=10)
            page.insert_text((40,150),'16. UNEP (2019). Global environmental assessment report.',fontsize=10)
            doc.save(pdf);doc.close()
            with pymupdf.open(pdf) as doc:
                lines=[]
                for n,b in enumerate(doc[0].get_text('dict')['blocks']):
                    for l in b.get('lines',[]):lines.append(dict(text=''.join(s['text'] for s in l['spans']),bbox=l['bbox'],block_id=n))
                x,y,r,b=lines[-1]['bbox']
                ref=dict(id='b16',reference_id='r',raw_citation='UNEP (2019). Global environmental assessment report.',
                         coordinates=[dict(page=1,x=x,y=y,width=r-x,height=b-y)],organization_candidate={'x':True},
                         semantic_review=dict(role='author',boundary='clean',author_names=['UNEP'],year='2019'))
                idx=dict(document_id='doc',references=[ref],contexts=[],occurrences=[])
                changes=recover(pdf,idx,[dict(page=1,lines=lines)])
                self.assertEqual(len(changes),2)
                self.assertEqual(len(idx['occurrences']),2)
                self.assertTrue(all(o['expanded_numbers']==[15,16,17] for o in idx['occurrences']))
                self.assertNotEqual(idx['occurrences'][0]['location_id'],idx['occurrences'][1]['location_id'])

    def test_joint_author_year_without_comma_and_reference_not_counted(self):
        with tempfile.TemporaryDirectory() as temp:
            pdf=Path(temp)/'p.pdf';doc=pymupdf.open();page=doc.new_page()
            page.insert_text((40,60),'Used (UNEP and AMAP 2019).',fontsize=10)
            page.insert_text((40,150),'UNEP and AMAP (2019). Report.',fontsize=10)
            doc.save(pdf);doc.close()
            with pymupdf.open(pdf) as doc:
                lines=[]
                for n,b in enumerate(doc[0].get_text('dict')['blocks']):
                    for l in b.get('lines',[]):lines.append(dict(text=''.join(s['text'] for s in l['spans']),bbox=l['bbox'],block_id=n))
            ref=dict(id='b',reference_id='r',raw_citation='UNEP and AMAP (2019). Report.',
                     coordinates=[dict(page=1,bbox=lines[-1]['bbox'])],organization_candidate={'x':True},
                     semantic_review=dict(role='author',boundary='clean',author_names=['UNEP','AMAP'],year='2019'))
            idx=dict(document_id='doc',references=[ref],contexts=[],occurrences=[])
            changes=recover(pdf,idx,[dict(page=1,lines=lines)])
            self.assertEqual(len(changes),1)
            self.assertEqual(idx['occurrences'][0]['raw_marker'],'UNEP and AMAP 2019')
