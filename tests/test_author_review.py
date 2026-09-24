import tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from paper_citation_pipeline.author_review import review_authors

class AuthorReviewTests(unittest.TestCase):
 def index(self):
  return {'references':[{'reference_id':'r','raw_citation':'UNEP-OtherUnit, 2025. Report.', 'organization_candidate':{'canonical_name':'UNEP','evidence':[],'identity_status':'candidate_related_organization_scope'}}]}
 def test_author_evidence_cached_and_no_duplicate_spend(self):
  with tempfile.TemporaryDirectory() as d, patch('paper_citation_pipeline.author_review.config',return_value={}), patch('paper_citation_pipeline.author_review.Client') as cls:
   # A nonempty configuration represents enabled API.
   with patch('paper_citation_pipeline.author_review.config',return_value={'model':'test'}):
    cls.return_value.request.return_value=({'role':'author','evidence':'UNEP-OtherUnit','reason':'署名位于年份之前'}, {'usage':{'total_tokens':12}})
    idx=self.index();self.assertEqual(review_authors(idx,'config',d),[])
    self.assertEqual(idx['references'][0]['organization_candidate']['author_role'],'author_or_coauthor')
    review_authors(self.index(),'config',d);self.assertEqual(cls.return_value.request.call_count,1)
 def test_invented_evidence_rejected(self):
  with tempfile.TemporaryDirectory() as d, patch('paper_citation_pipeline.author_review.config',return_value={'model':'test'}), patch('paper_citation_pipeline.author_review.Client') as cls:
   cls.return_value.key=None
   cls.return_value.request.return_value=({'role':'author','evidence':'invented author','reason':'x'}, {})
   idx=self.index();self.assertEqual(review_authors(idx,'config',d)[0]['code'],'author_identity_unresolved')
   self.assertNotIn('author_role',idx['references'][0]['organization_candidate'])
 def test_missing_api_retains_candidate(self):
  with tempfile.TemporaryDirectory() as d:
   idx=self.index();self.assertEqual(len(review_authors(idx,None,d)),1);self.assertTrue(idx['references'][0]['organization_candidate'])
