import unittest
from paper_citation_pipeline.organization_reference_audit import scan, reconcile

TARGET={'organization_id':'UNEP','canonical_name':'United Nations Environment Programme',
        'aliases':[{'name':'UN Environment'},{'name':'UNEP-WCMC'}]}

def line(text,y):return {'text':text,'bbox':[10,y,280,y+9],'block_id':0}
def coord(y):return {'page':1,'bbox':[10,y,280,y+9]}
def ref(ident,raw,y,boundary='clean',role='author'):
    return {'reference_id':ident,'raw_citation':raw,'coordinates':[coord(y)],
            'semantic_review':{'role':role,'boundary':boundary}}

class OrganizationReferenceAuditTests(unittest.TestCase):
    def test_independent_cross_line_name_inventory_and_word_boundaries(self):
        pages=[{'page':1,'lines':[line('References',10),line('UN',30),line('Environment (2018). Water report.',40),line('UNEPO and XUNEP are not matches.',60)]}]
        result=scan(pages,[],TARGET)
        self.assertEqual(result['name_hit_count'],1)
        self.assertEqual(result['reference_region_name_hit_count'],1)
        self.assertEqual(len(result['hits'][0]['line_ids']),2)
        audit=reconcile(result,{'references':[]},[],TARGET)
        self.assertEqual(len(audit['unmapped_reference_name_hits']),1)
        self.assertTrue(audit['zero_result_requires_review'])

    def test_reference_only_and_recovered_duplicate_are_not_lost(self):
        raw='UNEP-WCMC and IUCN (2020). Protected Planet.'
        pages=[{'page':1,'lines':[line('References',10),line(raw,30)]}]
        refs=[ref('short',raw[:35],30,'truncated'),ref('full',raw,30)]
        audit=reconcile(scan(pages,refs,TARGET),{'references':refs},[],TARGET)
        self.assertEqual(audit['reference_entry_count'],1)
        self.assertEqual(audit['entries'][0]['reference_id'],'full')
        self.assertEqual(audit['entries'][0]['status'],'pending_body_location')
        self.assertTrue(audit['zero_result_requires_review'])

    def test_filtered_publisher_body_links_remain_pending_without_authorship(self):
        refs=[ref('r','Smith (2008). UNEP report.',30,role='publisher')]
        pages=[{'page':1,'lines':[line('References',10),line(refs[0]['raw_citation'],30)]}]
        idx={'references':refs,'occurrences':[{'location_id':'o','raw_marker':'[13]','paragraph_id':'p','links':[{'reference_id':'r'}]}],
             'contexts':[{'id':'p','text':'Findings [13].'}]}
        audit=reconcile(scan(pages,refs,TARGET),idx,[],TARGET)
        self.assertEqual(audit['unexported_body_use_count'],1)
        self.assertEqual(audit['entries'][0]['reviewed_role'],'publisher')
        self.assertEqual(audit['entries'][0]['status'],'pending_inclusion_decision')
        self.assertEqual(refs[0]['semantic_review']['role'],'publisher')
        linked=reconcile(scan(pages,refs,TARGET),idx,[{'report_candidate_id':'r','location_id':'o'}],TARGET)
        self.assertEqual(linked['entries'][0]['status'],'linked_candidates')
        self.assertEqual(linked['unexported_body_use_count'],0)

    def test_no_text_and_unlocated_region_never_certify_zero(self):
        for pages in ([{'page':1,'lines':[]}],[{'page':1,'lines':[line('Ordinary body.',10)]}]):
            audit=reconcile(scan(pages,[],TARGET),{'references':[]},[],TARGET)
            self.assertTrue(audit['coverage_pending'])
            self.assertTrue(audit['zero_result_requires_review'])
        pages=[{'page':1,'lines':[line('References',10),line('Smith (2020). Other study.',30)]}]
        audit=reconcile(scan(pages,[],TARGET),{'references':[]},[],TARGET)
        self.assertTrue(audit['no_name_match_in_available_text'])
        self.assertTrue(audit['zero_result_requires_review'])
