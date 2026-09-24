import copy,sys,tempfile,unittest
from pathlib import Path
import pymupdf
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/paper_citation_pipeline/engine/runtime'))
from reference_repairs import repair
from standardize_citations import normalize,unep_rows
from test_standardize import sample,ref

class FragmentTests(unittest.TestCase):
 def test_square_abbreviation_and_parentheses_keep_offsets(self):
  for label in ['United Nations Environment Programme [UNEP]','United Nations Environment Programme (UNEP)']:
   text=f'Evidence ({label}, 2024).'
   rows=unep_rows(normalize(sample(text,[ref('b0','United Nations Environment Programme (UNEP), 2024. Global Resources Outlook.','2024')]),'p'))
   self.assertEqual(len(rows),1);self.assertIn(label,rows[0]['raw_marker'])
 def test_join_requires_pdf_number_and_full_text(self):
  with tempfile.TemporaryDirectory() as tmp:
   pdf=Path(tmp)/'p.pdf';doc=pymupdf.open();page=doc.new_page()
   lines=['[3] U.N. Environment. Global Status Report 2024/2025','| UNEP - UN Environment Programme, 2025.','https://www.unep.org/resources/report.']
   page.insert_text((40,70),'References',fontsize=9)
   for y,t in zip((100,115,130),lines):page.insert_text((40,y),t,fontsize=9)
   doc.save(pdf);doc.close()
   with pymupdf.open(pdf) as doc:
    blocks=doc[0].get_text('dict')['blocks'];plines=[l for b in blocks for l in b.get('lines',[])][1:]
   def coord(line):
    x,y,r,b=line['bbox'];return {'page':1,'x':x,'y':y,'width':r-x,'height':b-y}
   c=[coord(l) for l in plines];raw=' '.join(lines)[4:]
   refs=[dict(ref('b2',lines[0][4:],'2024'),coordinates=[c[0]]),
         dict(ref('b3',' '.join(lines[1:]),'2025'),coordinates=c[1:])]
   x=min(r['x'] for r in c);y=min(r['y'] for r in c);r=max(v['x']+v['width'] for v in c);b=max(v['y']+v['height'] for v in c)
   item={'self_ref':'#/texts/1','label':'list_item','text':raw,'marker':'[3]',
         'prov':[{'page_no':1,'bbox':{'l':x,'t':y,'r':r,'b':b,'coord_origin':'TOPLEFT'}}]}
   data=sample('Evidence [3].',refs)
   data['docling']={'document':{'body':{'children':[{'$ref':'#/texts/0'},{'$ref':'#/texts/1'}]},
     'texts':[{'self_ref':'#/texts/0','label':'section_header','text':'References'},item]}}
   original=copy.deepcopy(data);working,changes=repair(pdf,data)
   self.assertEqual(data,original);self.assertEqual(len(changes),1)
   joined=working['bibliography'][0];self.assertEqual(len(working['bibliography']),1)
   self.assertEqual(joined['numeric_label'],3);self.assertEqual(joined['year'],'2025')
   self.assertEqual(joined['raw_citation'],raw)
   item['marker']='[4]';working,changes=repair(pdf,data)
   self.assertEqual(changes,[]);self.assertEqual(len(working['bibliography']),2)
 def test_verified_math_interval_group_is_not_citation_but_range_is(self):
  group={'id':'g','raw_marker':'[3–5]','source':'original_pdf_characters','page':1,'bboxes':[[1,2,3,4]],
         'origin':'top-left','unit':'PDF point','expanded_numbers':[3,4,5],
         'numeric_targets':[{'number':3,'target_ids':['b2']}],'citation_ids':[]}
  d=sample('Evidence [3–5].',[ref('b2','UNEP, 2024. Report.','2024')],groups=[group])
  self.assertEqual(len(unep_rows(normalize(d,'p'))),1)
  group['citation_validity']='mathematical_set_membership_interval'
  self.assertEqual(unep_rows(normalize(d,'p')),[])
 def test_dash_normalization_does_not_normalize_different_digits(self):
  from docling_bibliography import compact
  self.assertEqual(compact('Bend the Trend – Pathways'),compact('Bend the Trend -Pathways'))
  self.assertNotEqual(compact('Report 2024'),compact('Report 2025'))

if __name__=='__main__':unittest.main()
