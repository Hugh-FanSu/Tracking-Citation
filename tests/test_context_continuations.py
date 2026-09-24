"""Paragraph restoration requires independent, complete PDF layout evidence."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path
import pymupdf
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/paper_citation_pipeline/engine/runtime'))
from context_repair import repair_contexts

class ContinuationTests(unittest.TestCase):
    def fixture(self,indent=False,wrong_text=False,kind='p',column=False,unfinished=False,fragment=False,full_context=False):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'paper.pdf';pdf=pymupdf.open();pdf.new_page(width=600,height=800)
            if not column:pdf.new_page(width=600,height=800)
            a=['These findings cite UNEP (2024) and support the evidence',
               'The research provides training and necessary quality control']
            b=['training, while independent partners provide support.',
               'The resulting collaboration benefits local communities.']
            if unfinished:b[-1]=b[-1].rstrip('.')
            for i,text in enumerate(a):pdf[0].insert_text((40,690+i*12),text,fontsize=8)
            for i,text in enumerate(b):pdf[0 if column else 1].insert_text(((320 if column else 40)+(12 if indent and i==0 else 0),65+i*12),text,fontsize=8)
            pdf.save(path);pdf.close()
            with pymupdf.open(path) as pdf:
                first=[l for block in pdf[0].get_text('dict')['blocks'] for l in block.get('lines',[]) if l['bbox'][1]>600]
                second=[l for block in pdf[0 if column else 1].get_text('dict')['blocks'] for l in block.get('lines',[]) if l['bbox'][1]<100]
                def prov(n,ls):
                    r=pymupdf.Rect(ls[0]['bbox'])
                    for l in ls[1:]:r|=pymupdf.Rect(l['bbox'])
                    return {'page_no':n,'bbox':{'l':r.x0,'r':r.x1,'t':r.y0,'b':r.y1,'coord_origin':'TOPLEFT'}}
                coords=[{'page':1,'x':l['bbox'][0],'y':l['bbox'][1],'width':l['bbox'][2]-l['bbox'][0],'height':l['bbox'][3]-l['bbox'][1]} for l in first]
                block={'self_ref':'#/texts/0','label':'text','text':' '.join(a+b)+(' invented' if wrong_text else ''),'prov':[prov(1,first),prov(1 if column else 2,second)]}
            if fragment:
                block['prov']=block['prov'][1:];block['text']=' '.join(b)
            if full_context:
                a=a+b
            p={'id':'p','kind':kind,'text':' '.join(a),'coordinates':coords}
            if fragment and not full_context:
                p['source']='original_pdf_text_blocks'
            row={'record_id':'r','paragraph_id':'p','paragraph_text':p['text'],'offsets':{'start':19},'previous_paragraph':None,'next_paragraph':None}
            if full_context:row['offsets']['start']=p['text'].index('training, while')+75
            index={'contexts':[p]};before=copy.deepcopy(index)
            changes=repair_contexts(path,index,[row],{'texts':[block]})
            self.assertEqual(before,index)
            return row,changes,a,b
    def test_page_continuation_without_next_parser_context(self):
        row,changes,a,b=self.fixture()
        self.assertEqual(row['paragraph_text'],' '.join(a+b));self.assertEqual(changes[0]['kind'],'restore_pdf_verified_docling_paragraph')
    def test_column_continuation(self):
        row,changes,a,b=self.fixture(column=True)
        self.assertEqual(row['paragraph_text'],' '.join(a+b));self.assertTrue(changes)
    def test_misclassified_caption_can_restore_body_envelope(self):
        row,changes,a,b=self.fixture(kind='figDesc');self.assertTrue(changes)
    def test_indented_next_page_must_not_join(self):
        row,changes,a,b=self.fixture(indent=True);self.assertEqual(changes,[]);self.assertEqual(row['paragraph_text'],' '.join(a))
    def test_pdf_recovered_context_appends_verified_page_fragment(self):
        row,changes,a,b=self.fixture(fragment=True)
        self.assertEqual(row['paragraph_text'],' '.join(a+b))
        self.assertEqual(changes[0]['kind'],'restore_pdf_page_continuation')
    def test_page_fragment_does_not_drop_existing_opening(self):
        row,changes,a,b=self.fixture(fragment=True,full_context=True)
        self.assertEqual(row['paragraph_text'],' '.join(a));self.assertEqual(changes,[])
    def test_incomplete_docling_page_fragment_is_not_an_envelope(self):
        row,changes,a,b=self.fixture(unfinished=True);self.assertEqual(changes,[])
    def test_docling_text_must_match_original_pdf(self):
        row,changes,a,b=self.fixture(wrong_text=True);self.assertEqual(changes,[])

if __name__=='__main__':unittest.main()
