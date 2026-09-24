import copy,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import pymupdf
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/paper_citation_pipeline/engine/runtime'))
from context_repair import repair_contexts
from recall_audit import audit
class ContextTests(unittest.TestCase):
 def run_context(self,indent=False,shared=True):
  with tempfile.TemporaryDirectory() as tmp:
   pdf=Path(tmp)/'p.pdf';doc=pymupdf.open();p=doc.new_page()
   texts=['These observations support the documented conclusion.',
          'Another sentence supports the documented conclusion.',
          'Further observations support a different explanation.',
          'The remaining evidence is retained without alteration.']
   for i,t in enumerate(texts):p.insert_text((52 if indent and i==2 else 40,80+12*i),t,fontsize=9)
   doc.save(pdf);doc.close()
   with pymupdf.open(pdf) as doc:
    lines=[l for b in doc[0].get_text('dict')['blocks'] for l in b.get('lines',[])]
   coords=[dict(page=1,x=l['bbox'][0],y=l['bbox'][1],width=l['bbox'][2]-l['bbox'][0],height=l['bbox'][3]-l['bbox'][1]) for l in lines]
   # Case A: parser merged two printed paragraphs. Case B: parser split a continuous one.
   cut=4 if indent else 3
   first=dict(id='p1',kind='p',section_id='s',text=' '.join(texts[:cut]),coordinates=coords[:cut],next_paragraph_id='p2')
   second=dict(id='p2',kind='p',section_id='s',text=' '.join(texts[cut:]),coordinates=coords[cut:],next_paragraph_id=None)
   row=dict(record_id='r1',paragraph_id='p1',paragraph_text=first['text'],previous_paragraph=None,next_paragraph=second['text'],offsets={'start':0})
   idx={'contexts':[first,second]};before=copy.deepcopy(idx)
   changes=repair_contexts(pdf,idx,[row],{'texts':[{'label':'text','text':' '.join(texts) if shared else 'unrelated'}]})
   self.assertEqual(idx,before);return row,changes,texts
 def test_indented_new_paragraph_split_with_evidence(self):
  row,changes,texts=self.run_context(indent=True)
  self.assertEqual(row['paragraph_text'],' '.join(texts[:2]));self.assertEqual(row['next_paragraph'],' '.join(texts[2:]))
  self.assertEqual(changes[0]['kind'],'split_context_at_pdf_indent')
 def test_continuation_requires_shared_docling_and_pdf_lines(self):
  row,changes,texts=self.run_context()
  self.assertEqual(row['paragraph_text'],' '.join(texts));self.assertEqual(changes[0]['kind'],'join_context_continuation')
 def test_no_join_without_independent_docling_support(self):
  row,changes,texts=self.run_context(shared=False);self.assertEqual(changes,[])
  self.assertEqual(row['paragraph_text'],' '.join(texts[:3]))
class RecallTests(unittest.TestCase):
 def test_repeated_author_year_gap_even_when_one_link_exists(self):
  pages=[{'page':1,'text':'Evidence (UNEP, 2024). Again (UNEP, 2024).'}]
  rows=[{'year_label_from_raw':'2024','pdf_pages':[1],'location_id':'one'}]
  r=audit(pages,{'references':[]},rows);self.assertEqual(r['findings'][0]['pdf_markers'],2)
 def test_unknown_compound_author_is_not_silently_accepted(self):
  r=audit([{'page':1,'text':'(UNEP/NEWPANEL, 2024).'}],{'references':[]},[])
  self.assertTrue(any(f['code']=='unknown_joint_author' for f in r['findings']))
 def test_bibliography_entry_not_counted_as_body(self):
  raw='UNEP. (2024). A long report about the global environment and sustainable futures.'
  r=audit([{'page':1,'text':raw}],{'references':[{'organization_candidate':True,'raw_citation':raw,'coordinates':[{'page':1}]}]},[])
  self.assertEqual(r['inventory'],[])
if __name__=='__main__':unittest.main()
