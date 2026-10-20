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
