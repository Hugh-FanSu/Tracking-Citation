import unittest
from unittest.mock import patch
from paper_citation_pipeline.reference_recovery import recover_missing
class ReferenceRecoveryTests(unittest.TestCase):
 def run_case(self,ids):
  lines=[{'id':'l1','text':'UNEP. 2021. Adaptation Gap Report','page':1,'bbox':[0,0,10,10]}, {'id':'l2','text':'Nairobi: UNEP.','page':1,'bbox':[0,10,10,20]}]
  class Reviewer:
   cfg=True
   def request(self,stage,prompt,payload,validate):
    result={'entries':[{'line_ids':ids}]};validate(result);return {'status':'completed','result':result,'fingerprint':'test'}
  idx={'document_id':'doc','references':[]}
  with patch('paper_citation_pipeline.reference_recovery.source_lines',return_value=lines),patch('paper_citation_pipeline.reference_recovery.select_region',return_value=(lines,{})),patch('paper_citation_pipeline.reference_recovery.overlapping_windows',return_value=[(lines,['l1','l2'])]),patch('paper_citation_pipeline.reference_recovery.review_references',return_value={'decisions':{}}):
   recover_missing(idx,[],{'aliases':['UNEP']},Reviewer())
  return idx
 def test_exact_source_preserved(self):
  idx=self.run_case(['l1','l2']);self.assertEqual(idx['references'][0]['raw_citation'],'UNEP. 2021. Adaptation Gap Report Nairobi: UNEP.')
  self.assertIsNone(idx['references'][0]['organization_candidate'])
 def test_unknown_lines_rejected(self):
  with self.assertRaises(ValueError):self.run_case(['invented'])
 def test_reordered_lines_rejected(self):
  with self.assertRaises(ValueError):self.run_case(['l2','l1'])
 def test_recovered_mixed_original_is_not_counted_twice(self):
  lines=[{'id':'l1','text':'UNEP. 2021. Adaptation Gap Report','page':1,'bbox':[0,0,10,10]}]
  class Reviewer:
   cfg=True
   def request(self,stage,prompt,payload,validate):
    value={'entries':[{'line_ids':['l1']}]};validate(value)
    return {'status':'completed','result':value,'fingerprint':'test'}
  old={'reference_id':'old','raw_citation':'Smith. Other study. UNEP. 2021. Adaptation Gap Report','semantic_review':{'boundary':'mixed'},'organization_candidate':{'organization_id':'UNEP'}}
  idx={'document_id':'doc','references':[old]}
  def review(index,*args):
   for r in index['references']:r['semantic_review']={'role':'author','boundary':'clean'}
   return {'decisions':{}}
  with patch('paper_citation_pipeline.reference_recovery.source_lines',return_value=lines),patch('paper_citation_pipeline.reference_recovery.select_region',return_value=(lines,{})),patch('paper_citation_pipeline.reference_recovery.overlapping_windows',return_value=[(lines,['l1'])]),patch('paper_citation_pipeline.reference_recovery.review_references',side_effect=review):
   recover_missing(idx,[],{'aliases':['UNEP']},Reviewer())
  self.assertIsNone(old['organization_candidate'])
  self.assertEqual(old['target_evidence_resolved_by'],[idx['references'][1]['reference_id']])
  self.assertIn('Smith.',old['raw_citation'])

class NativeDuplicateTests(unittest.TestCase):
 def test_bullet_reference_fallback_after_model_omission(self):
  lines=[{'id':'h','text':'References','page':23,'bbox':[0,0,100,10]},
         {'id':'b1','text':'•','page':23,'bbox':[0,10,10,20]},
         {'id':'l1','text':'International Union for Conservation of Nature & United Nations Environment','page':23,'bbox':[20,10,100,20]},
         {'id':'l2','text':'Programme - World Conservation Monitoring Centre (UNEP-WCMC) (2022) Protected Planet.','page':23,'bbox':[20,20,100,30]},
         {'id':'b2','text':'•','page':23,'bbox':[0,30,10,40]},
         {'id':'l3','text':'Smith (2020) Report published by UNEP.','page':23,'bbox':[20,30,100,40]}]
  class Reviewer:
   cfg=True
   def request(self,stage,prompt,payload,validate):
    result={'entries':[]};validate(result)
    return {'status':'completed','result':result,'fingerprint':'test'}
  idx={'document_id':'doc','references':[]}
  with patch('paper_citation_pipeline.reference_recovery.source_lines',return_value=lines),\
       patch('paper_citation_pipeline.reference_recovery.select_region',return_value=(lines,{'independently_located':True})),\
       patch('paper_citation_pipeline.reference_recovery.overlapping_windows',return_value=[(lines,[x['id'] for x in lines])]),\
       patch('paper_citation_pipeline.reference_recovery.review_references',return_value={'decisions':{}}):
   changes,_=recover_missing(idx,[],{'aliases':['United Nations Environment Programme','UNEP-WCMC']},Reviewer())
  self.assertEqual(len(changes),1)
  self.assertEqual(idx['references'][0]['native_line_ids'],['l1','l2'])
  self.assertEqual(idx['references'][0]['source'],'native_bullet_author_year')

 def test_adjacent_printed_references_split_at_number_labels(self):
  from paper_citation_pipeline.reference_recovery import split_printed_entries
  lines=[{'id':'a','text':'8 \u0007UNDP. Delta report.'},
         {'id':'b','text':'9 \u0007United Nations Environment Programme. Ogoniland.'},
         {'id':'c','text':'Nairobi, Kenya: UN; 2011.'}]
  self.assertEqual([[line['id'] for line in group] for group in split_printed_entries(lines)],
                   [['a'],['b','c']])

 def test_same_entry_requires_full_text_and_physical_location(self):
  from paper_citation_pipeline.reference_recovery import same_entry
  ref={'raw_citation':'Short. 2005. Report. pp. 13-15.','coordinates':[{'page':1,'bbox':[0,0,100,10]}],'semantic_review':{'boundary':'clean'}}
  self.assertTrue(same_entry('12. Short. 2005. Report. pp. 13–15.',ref['coordinates'],ref))
  self.assertFalse(same_entry('12. Short. 2005. Other report. pp. 13–15.',ref['coordinates'],ref))
  self.assertFalse(same_entry('12. Short. 2005. Report. pp. 13–15.',[{'page':2,'bbox':[0,0,100,10]}],ref))

 def test_recovery_sends_only_nearby_inventory_to_model(self):
  lines=[{'id':'l1','text':'UNEP. 2021. Adaptation Gap Report','page':1,'bbox':[0,0,100,10]}]
  near={'reference_id':'near','raw_citation':'Adjacent entry','coordinates':[{'page':1,'bbox':[0,0,100,10]}]}
  far={'reference_id':'far','raw_citation':'Another page '+('x'*30000),'coordinates':[{'page':2,'bbox':[0,0,100,10]}]}
  seen=[]
  class Reviewer:
   cfg=True
   def request(self,stage,prompt,payload,validate):
    seen.extend(item['raw'] for item in payload['inventory'])
    return {'status':'completed','result':{'entries':[]},'fingerprint':'test'}
  idx={'document_id':'doc','references':[near,far]}
  with patch('paper_citation_pipeline.reference_recovery.source_lines',return_value=lines),patch('paper_citation_pipeline.reference_recovery.select_region',return_value=(lines,{})),patch('paper_citation_pipeline.reference_recovery.overlapping_windows',return_value=[(lines,['l1'])]):
   recover_missing(idx,[],{'aliases':['UNEP']},Reviewer())
  self.assertEqual(seen,['Adjacent entry'])

 def test_valid_numbered_entries_survive_an_invalid_sibling_in_model_batch(self):
  lines=[{'id':'p13:l24','text':'\t 25\t UNEP. First report.','page':13,'bbox':[0,0,100,10]},
         {'id':'p13:l28','text':'\t 26\t UNEP. Second report.','page':13,'bbox':[0,20,100,30]}]
  class Reviewer:
   cfg=True
   def request(self,stage,prompt,payload,validate):
    result={'entries':[{'line_ids':['p13:l24']},{'line_ids':['missing']},{'line_ids':['p13:l28']}]}
    validate(result)
    self.asserted=result
    return {'status':'completed','result':result,'fingerprint':'test'}
  reviewer=Reviewer()
  idx={'document_id':'doc','references':[]}
  with patch('paper_citation_pipeline.reference_recovery.source_lines',return_value=lines),\
       patch('paper_citation_pipeline.reference_recovery.select_region',return_value=(lines,{})),\
       patch('paper_citation_pipeline.reference_recovery.overlapping_windows',return_value=[(lines,['p13:l28'])]),\
       patch('paper_citation_pipeline.reference_recovery.review_references',return_value={'decisions':{}}):
   changes,_=recover_missing(idx,[],{'aliases':['UNEP']},reviewer)
  self.assertEqual(len(changes),2)
  self.assertEqual(len(reviewer.asserted['discarded_entries']),1)

 def test_author_year_entry_in_overlap_is_accepted_after_independent_heading(self):
  lines=[{'id':'p23:l15','text':'FAO, UNEP (2020) The state of the world forests.',
          'page':23,'bbox':[0,0,100,10]}]
  class Reviewer:
   cfg=True
   def request(self,stage,prompt,payload,validate):
    result={'entries':[{'line_ids':['p23:l15']}]};validate(result)
    return {'status':'completed','result':result,'fingerprint':'test'}
  idx={'document_id':'doc','references':[]}
  with patch('paper_citation_pipeline.reference_recovery.source_lines',return_value=lines),\
       patch('paper_citation_pipeline.reference_recovery.select_region',return_value=(lines,{'independently_located':True})),\
       patch('paper_citation_pipeline.reference_recovery.overlapping_windows',return_value=[(lines,[])]),\
       patch('paper_citation_pipeline.reference_recovery.review_references',return_value={'decisions':{}}):
   changes,_=recover_missing(idx,[],{'aliases':['UNEP']},Reviewer())
  self.assertEqual(len(changes),1)

 def test_excel_escapes_pdf_control_character_without_changing_json(self):
  from paper_citation_pipeline.excel import excel_safe_text
  self.assertEqual(excel_safe_text('9 \u0007UNEP'), '9 \\u0007UNEP')
