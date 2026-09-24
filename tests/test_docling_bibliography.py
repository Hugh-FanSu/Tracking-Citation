import copy,json,sys,tempfile,unittest
from pathlib import Path
import pymupdf
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/paper_citation_pipeline/engine/runtime'))
from reference_repairs import repair
from standardize_citations import normalize,unep_rows
from test_standardize import sample

class DoclingBibliographyTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.pdf=Path(self.temp.name)/'paper.pdf'
  self.raw=['UNEP. (2024). Emissions gap report 2024. United Nations Environment Programme.',
            'UNEP. (2025). Global environment outlook 7. United Nations Environment Programme.']
  doc=pymupdf.open();page=doc.new_page();page.insert_text((40,30),'Journal header',fontsize=9);page.insert_text((40,110),'References',fontsize=9)
  page=doc.new_page();page.insert_text((40,30),'Journal header',fontsize=9)
  for y,text in zip((110,140),self.raw):page.insert_text((40,y),text,fontsize=9)
  doc.save(self.pdf);doc.close();texts=[]
  with pymupdf.open(self.pdf) as pdf:
   for n,p in enumerate(pdf,1):
    for block in p.get_text('dict')['blocks']:
     for line in block.get('lines',[]):
      text=''.join(s['text'] for s in line['spans']);x,y,r,b=line['bbox']
      texts.append({'self_ref':f'#/texts/{len(texts)}','text':text,'label':'section_header' if text in ['References','Journal header'] else 'list_item',
        'prov':[{'page_no':n,'bbox':{'l':x,'t':p.rect.height-y,'r':r,'b':p.rect.height-b,'coord_origin':'BOTTOMLEFT'}}]})
  self.data=sample('Evidence (UNEP, 2024; UNEP, 2025).',[])
  self.data['paragraphs'].append({'id':'bibliography_misclassified','kind':'p','section_id':None,'coordinates':[],'text':' '.join(self.raw)})
  self.data['docling']={'document':{'body':{'children':[{'$ref':t['self_ref']} for t in texts]},'texts':texts}}
 def tearDown(self):self.temp.cleanup()
 def test_recover_two_and_do_not_count_bibliography_as_citations(self):
  original=copy.deepcopy(self.data);working,changes=repair(self.pdf,self.data)
  self.assertEqual(self.data,original);self.assertEqual(len(changes),2)
  self.assertEqual(len(working['bibliography']),2)
  self.assertEqual(working['reference_region_audit']['status'],'repaired')
  rows=unep_rows(normalize(working,'paper'));self.assertEqual(len(rows),2)
  self.assertEqual({r['paragraph_id'] for r in rows},{'p1'})
  self.assertTrue(all(c['reference']['coordinates'][0]['page']==2 for c in changes))
 def test_no_references_heading_no_recovery(self):
  self.data['docling']['document']['texts'][1]['text']='Discussion'
  working,changes=repair(self.pdf,self.data);self.assertEqual(changes,[])
 def test_requires_pdf_evidence(self):
  self.data['docling']['document']['texts'][-1]['text']=self.raw[-1].replace('outlook 7','fabricated report')
  working,changes=repair(self.pdf,self.data);self.assertEqual(len(changes),1)
  self.assertEqual(working['reference_region_audit']['status'],'needs_attention')
  self.assertEqual(working['reference_region_audit']['entries'][-1]['reason'],'original_pdf_text_not_verified')
 def test_no_duplicate_existing_reference(self):
  self.data['bibliography']=[{'id':'existing','raw_citation':self.raw[0],'title':'Emissions gap report 2024','year':'2024'}]
  working,changes=repair(self.pdf,self.data);self.assertEqual(len(changes),1);self.assertEqual(len(working['bibliography']),2)
 def test_bibliography_alone_does_not_create_body_citation(self):
  self.data['paragraphs']=self.data['paragraphs'][1:]
  working,changes=repair(self.pdf,self.data);self.assertEqual(len(changes),2)
  self.assertEqual(unep_rows(normalize(working,'paper')),[])

if __name__=='__main__':unittest.main()
