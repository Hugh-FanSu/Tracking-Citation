import copy
import unittest
from paper_citation_pipeline.diagnostic_reconciliation import reconcile

class ReconciliationTests(unittest.TestCase):
 def test_exact_location_only_and_history_preserved(self):
  index={'references':[{'reference_id':'r','semantic_review':{'boundary':'clean','role':'author'}}],
   'organization_unlinked_candidates':[{'paragraph_id':'p','marker':'UNEP 2021','offsets':[5,14]}],
   'occurrences':[{'location_id':'o','paragraph_id':'p','raw_marker':'UNEP 2021','offsets':{'start':5,'end':14},'links':[{'reference_id':'r'}]}]}
  wrong=copy.deepcopy(index);wrong['occurrences'][0]['offsets']['start']=20
  self.assertEqual(reconcile(wrong),[])
  self.assertEqual(len(wrong['organization_unlinked_candidates']),1)
  self.assertEqual(len(reconcile(index)),1)
  self.assertEqual(index['organization_unlinked_candidates'],[])
  self.assertEqual(index['resolved_diagnostics'][0]['resolved_by_location_id'],'o')
  self.assertEqual(reconcile(index),[])

 def test_group_citation_resolves_only_matching_author_year(self):
  index={'references':[{'reference_id':'r','semantic_review':{'boundary':'clean','role':'author','year':'2018','author_names':['UNEP']}}],
   'organization_unlinked_candidates':[{'paragraph_id':'p','marker':'UNEP 2018','offsets':[1,10]}],
   'occurrences':[{'location_id':'o','paragraph_id':'p','raw_marker':'(UNEP 2018, Other 2020)','offsets':{'start':0,'end':23},'links':[{'reference_id':'r'},{'reference_id':'other'}]}]}
  wrong=copy.deepcopy(index);wrong['references'][0]['semantic_review']['year']='2019'
  self.assertEqual(reconcile(wrong),[])
  self.assertEqual(len(reconcile(index)),1)
