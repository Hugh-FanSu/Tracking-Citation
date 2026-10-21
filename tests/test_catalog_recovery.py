import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/'src/paper_citation_pipeline/engine/runtime'))
from paper_citation_pipeline.catalog_recovery import recover, recover_author_year_uses
class CatalogRecoveryTests(unittest.TestCase):
 def test_catalogued_author_year_marker_missing_from_parser_is_found_in_pdf(self):
  import tempfile,pymupdf
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'paper.pdf';doc=pymupdf.open();body=doc.new_page()
   body.insert_text((60,90),'Eagles et al. (2002) outline the risks.')
   body.insert_text((60,110),'Guidance (e.g., Eagles et al., 2002; Smith, 2004) informed the plan.')
   doc.new_page().insert_text((60,90),'Eagles, P. (2002) Sustainable Tourism in Protected Areas.')
   doc.save(path);doc.close()
   ref={'id':'r','reference_id':'r','raw_citation':'Eagles, P. (2002) Sustainable Tourism in Protected Areas.',
        'authors':[{'family':'Eagles'}],'year_label':'2002','coordinates':[{'page':2,'x':60,'y':70,'width':350,'height':25}],
        'catalog_match_evidence':{'status':'已匹配'},'organization_candidate':{'organization_id':'UNEP'},
        'semantic_review':{'role':'unrelated','boundary':'clean'}}
   index={'document_id':'doc','references':[ref],'contexts':[],'occurrences':[]}
   changes=recover_author_year_uses(index,str(path))
   self.assertEqual(len(changes),2)
   self.assertEqual([o['raw_marker'] for o in index['occurrences']],['Eagles et al. (2002)','Eagles et al., 2002'])

 def test_distinctive_fao_report_same_year_is_catalog_source(self):
  r={'reference_id':'r','raw_citation':'FAO. Global Assessment of Soil Pollution: Report. Rome, FAO. In.; 2021.',
     'semantic_review':{'role':'unrelated','boundary':'clean','title':'Global Assessment of Soil Pollution: Report. Rome, FAO','year':'2021'}}
  c={'rows':[{'title':'Global Assessment of Soil Pollution','url':'https://www.unep.org/resources/report/global-assessment-soil-pollution','date':'3 JUN 2021'}]}
  changes=recover({'references':[r]},c,{'organization_id':'UNEP','canonical_name':'United Nations Environment Programme'})
  self.assertEqual(len(changes),1)
  self.assertEqual(r['semantic_review']['role'],'unrelated')
  self.assertEqual(r['catalog_identity_basis'],'distinctive_title_and_matching_catalog_year')

 def test_other_edition_and_summary_are_not_promoted(self):
  c={'rows':[{'title':'The State of World Fisheries and Aquaculture','url':'https://www.unep.org/resources/report/state-world-fisheries-and-aquaculture','date':'6 JUL 2014'},
             {'title':'Global Assessment of Soil Pollution','url':'https://www.unep.org/resources/report/global-assessment-soil-pollution','date':'3 JUN 2021'}]}
  refs=[{'reference_id':'old','raw_citation':'FAO (2009). The State of World Fisheries and Aquaculture.',
         'semantic_review':{'role':'unrelated','boundary':'clean','title':'The State of World Fisheries and Aquaculture','year':'2009'}},
        {'reference_id':'summary','raw_citation':'Global Assessment of Soil Pollution: Summary for Policymakers. FAO 2021.',
         'semantic_review':{'role':'unrelated','boundary':'clean','title':'Global Assessment of Soil Pollution: Summary for Policymakers','year':'2021'}}]
  self.assertEqual(recover({'references':refs},c,{'organization_id':'UNEP','canonical_name':'United Nations Environment Programme'}),[])
  self.assertTrue(all('catalog_title_candidate' in ref for ref in refs))

 def test_personal_author_catalogued_source_included_without_changing_role(self):
  r={'reference_id':'r','raw_citation':'Short. 2005. Global distribution of seagrasses. In UNEP.','semantic_review':{'role':'publisher','boundary':'clean','title':'Global distribution of seagrasses','year':'2005'}}
  c={'rows':[{'title':'Global Distribution of Seagrasses','url':'https://www.unep.org/resources/publication/global-distribution-seagrasses','date':'20 DEC 2020'}]}
  changes=recover({'references':[r]},c,{'organization_id':'UNEP','canonical_name':'UNEP'})
  self.assertEqual(len(changes),1);self.assertEqual(r['semantic_review']['role'],'publisher');self.assertTrue(r['catalog_match_evidence']['notes'])
 def test_mixed_reference_not_promoted(self):
  r={'reference_id':'r','raw_citation':'UNEP','semantic_review':{'boundary':'mixed'}}
  self.assertEqual(recover({'references':[r]},{'rows':[]},{'organization_id':'UNEP','canonical_name':'UNEP'}),[])
 def test_generic_shared_title_is_not_identity(self):
  r={'reference_id':'r','title':'Demographic and Health Survey','raw_citation':'Kenya. 2014 Demographic and Health Survey. https://dhsprogram.com/report.pdf','semantic_review':{'role':'unrelated','boundary':'clean'}}
  c={'rows':[{'title':'Demographic and Health Survey','url':'https://www.unep.org/resources/report/demographic-and-health-survey','date':'2010'}]}
  self.assertEqual(recover({'references':[r]},c,{'organization_id':'UNEP','canonical_name':'UNEP'}),[])
  self.assertNotIn('organization_candidate',r)
  self.assertIn('catalog_title_candidate',r)

 def test_catalog_authors_use_real_names_without_changing_institution_role(self):
  class Reviewer:
   def request(self,stage,prompt,payload,validate):
    result={'author_names':['Short, T F.']};validate(result)
    return {'status':'completed','result':result,'fingerprint':'checked'}
  r={'reference_id':'r','raw_citation':'Short, T F. 2005. Global distribution of seagrasses. In UNEP.','semantic_review':{'role':'publisher','boundary':'clean','author_names':[],'title':'Global distribution of seagrasses','year':'2005'}}
  c={'rows':[{'title':'Global Distribution of Seagrasses','url':'https://www.unep.org/resources/publication/global-distribution-seagrasses','date':'20 DEC 2020'}]}
  recover({'references':[r]},c,{'organization_id':'UNEP','canonical_name':'UNEP'},Reviewer())
  self.assertEqual(r['semantic_review']['author_names'],['Short, T F.'])
  self.assertEqual(r['semantic_review']['role'],'publisher')
