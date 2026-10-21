import unittest
from paper_citation_pipeline.local_review import review_contexts
class ContextReuseTests(unittest.TestCase):
 def test_separate_reviewed_attribution_reuses_same_complete_paragraph(self):
  text='Plastic waste increased (UNEP 2018). UNEP found that packaging accounts for half.'
  first={'record_id':'one','report_candidate_id':'r','location_id':'l1','raw_marker':'(UNEP 2018)','paragraph_text':text,'pdf_pages':[1],'carrier':'paragraph'}
  second={**first,'record_id':'two','location_id':'l2','raw_marker':'UNEP found that packaging accounts for half.'}
  packet={'pdf_pages':[{'page':1,'lines':[{'text':text,'block_id':1,'bbox':[0,0,100,10]}]}],
          'citation_index':{'references':[{'reference_id':'r','raw_citation':'UNEP. 2018. Report.'}],'occurrences':[{'location_id':'l1','native_locator':{'page':1,'block_id':1}}, {'location_id':'l2','native_locator':{'page':1,'block_id':1},'semantic_attribution':{'fingerprint':'source-use'}}]},'target_candidates':[first,second]}
  class Reviewer:
   calls=0
   def request(self,stage,prompt,payload,validate):
    self.calls+=1
    value={'status':'complete','relevant':True,'segments':[{'start_line':'p1:l0','end_line':'p1:l0','end':None}],'reason':'Complete paragraph'}
    validate(value)
    return {'status':'completed','result':value,'fingerprint':'context'}
  reviewer=Reviewer();results=review_contexts(packet,reviewer)
  self.assertEqual(reviewer.calls,1);self.assertEqual(results['two']['reused_from_record'],'one')
  self.assertEqual(second['paragraph_text'],text)

 def test_other_page_or_missing_location_never_reuses(self):
  from paper_citation_pipeline.local_review import same_native_block
  p={'citation_index':{'occurrences':[{'location_id':'a','native_locator':{'page':1,'block_id':0}}, {'location_id':'b','native_locator':{'page':2,'block_id':0}}]}}
  self.assertFalse(same_native_block(p,{'location_id':'a'},{'location_id':'b'}))
  self.assertFalse(same_native_block(p,{'location_id':'missing'},{'location_id':'missing'}))

 def test_verified_spans_allow_same_physical_paragraph_not_same_text_elsewhere(self):
  from paper_citation_pipeline.local_review import same_native_block
  p={'pdf_pages':[{'page':1,'lines':[{'text':'UNEP reports results.','block_id':0,'bbox':[0,0,100,10]}]}], 'citation_index':{'occurrences':[{'location_id':'b','coordinates':[{'page':1,'bbox':[0,0,100,10]}]}]}}
  first={'semantic_context':{'segments':[{'start_line':'p1:l0','end_line':'p1:l0'}]}}
  self.assertTrue(same_native_block(p,first,{'location_id':'b'}))
  p['citation_index']['occurrences'][0]['coordinates'][0]['page']=2
  self.assertFalse(same_native_block(p,first,{'location_id':'b'}))
