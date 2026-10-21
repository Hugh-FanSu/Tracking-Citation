import unittest
from paper_citation_pipeline.collection_policy import classify
class PolicyTests(unittest.TestCase):
 def data(self,role='author',structure='sole',authors=None,matched=False):
  p={'citation_index':{'references':[{'reference_id':'r','semantic_review':{'role':role,'boundary':'clean','authorship_structure':structure,'author_names':authors or ['UNEP']}}]}}
  r={'report_candidate_id':'r','report_match':{'status':'matched' if matched else 'unmatched'}}
  return p,r
 def test_matched_has_priority(self):self.assertEqual(classify(*self.data(matched=True))['collection_tier'],1)
 def test_single_author(self):self.assertEqual(classify(*self.data())['collection_tier'],2)
 def test_joint_author(self):self.assertEqual(classify(*self.data(structure='joint',authors=['UNEP','AMAP']))['collection_tier'],3)
 def test_compound_cannot_be_sole(self):
  c=classify(*self.data(authors=['UNEP-WCMC']));self.assertEqual(c['collection_tier'],3);self.assertTrue(c['compound_author_flag'])
 def test_publisher_not_author(self):self.assertEqual(classify(*self.data(role='publisher'))['collection_tier'],0)
 def test_unknown_sole_status_is_not_tier_two(self):self.assertEqual(classify(*self.data(structure='uncertain'))['collection_tier'],3)
 def test_catalog_date_difference_preserved_without_rejecting_title_match(self):
  p,r=self.data(matched=True);r['report_match']['notes']=['年份不同'];self.assertEqual(classify(p,r)['collection_tier'],1);self.assertTrue(classify(p,r)['catalog_date_differs'])

 def test_full_signature_overrules_incomplete_model_sole_claim(self):
  p,r=self.data()
  p['citation_index']['references'][0]['verified_author_signature']={'text':'UNEP and AMAP','model_author_names_may_be_incomplete':True}
  result=classify(p,r)
  self.assertEqual(result['collection_tier'],3)
  self.assertEqual(result['author_signature'],'UNEP and AMAP')
