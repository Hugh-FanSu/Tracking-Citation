import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/'src/paper_citation_pipeline/engine/runtime'))
from paper_citation_pipeline.attribution_review import recover
class AttributionTests(unittest.TestCase):
 def run_case(self,quote,existing=False):
  text='In 2018, UNEP found that half of plastic waste came from packaging.'
  class Reviewer:
   cfg=True
   def request(self,stage,prompt,payload,validate):
    result={'uses':[{'block_id':'p1:b1','reference_id':'r','quote':quote,'reason':'Explicit attribution to the only UNEP 2018 reference'}]};validate(result)
    return {'status':'completed','result':result,'fingerprint':'fixture'}
  idx={'document_id':'doc','references':[{'id':'r','reference_id':'r','raw_citation':'UNEP. 2018. Single-use plastics.','semantic_review':{'role':'author','boundary':'clean'}}],'contexts':[],'occurrences':[]}
  if existing:idx['occurrences'].append({'raw_marker':'UNEP found' if existing is True else existing,'coordinates':[{'page':1,'x':0,'y':0,'width':100,'height':10}], 'links':[{'reference_id':'r'}]})
  pages=[{'page':1,'lines':[{'text':text,'block_id':1,'bbox':[0,0,100,10]}]}]
  changes=recover(idx,pages,{'canonical_name':'UNEP','aliases':['UNEP']},Reviewer())
  return idx,changes
 def test_exact_narrative_is_separate_occurrence(self):
  idx,changes=self.run_case('UNEP found that half of plastic waste came from packaging.')
  self.assertEqual(len(changes),1);self.assertEqual(idx['occurrences'][0]['links'][0]['reference_id'],'r')
 def test_invented_quote_rejected(self):
  with self.assertRaises(ValueError):self.run_case('UNEP found 75% of waste.')

 def test_existing_citation_contained_in_attribution_is_not_counted_twice(self):
  idx,changes=self.run_case("UNEP found that half of plastic waste came from packaging.",existing=True)
  self.assertEqual(changes,[]);self.assertEqual(len(idx["occurrences"]),1)

 def test_narrative_substring_of_formal_citation_is_not_counted_twice(self):
  idx,changes=self.run_case('UNEP found that half of plastic waste came from packaging.',
                            existing='In 2018, UNEP found that half of plastic waste came from packaging.')
  self.assertEqual(changes,[]);self.assertEqual(len(idx['occurrences']),1)

 def test_adjacent_numbered_citation_to_same_source_supersedes_narrative_use(self):
  text='The council includes FAO and UN Environment Programme (86), according to the cited source.'
  class Reviewer:
   cfg=True
   def request(self,stage,prompt,payload,validate):
    result={'uses':[{'block_id':'p2:b1','reference_id':'r','quote':'includes FAO and UN Environment Programme','reason':'Council composition'}]}
    validate(result);return {'status':'completed','result':result,'fingerprint':'fixture'}
  box={'page':2,'x':0,'y':0,'width':200,'height':12}
  idx={'document_id':'doc','references':[{'id':'r','reference_id':'r','raw_citation':'UN Environment Programme. 2020. One Health.',
       'semantic_review':{'role':'author','boundary':'clean'}}], 'contexts':[],
       'occurrences':[{'raw_marker':'(86)','coordinates':[box],'links':[{'reference_id':'r'}]}]}
  pages=[{'page':2,'lines':[{'text':text,'block_id':1,'bbox':[0,0,200,12]}]}]
  self.assertEqual(recover(idx,pages,{'canonical_name':'UN Environment Programme','aliases':['UN Environment Programme']},Reviewer()),[])
  self.assertEqual(len(idx['occurrences']),1)

 def test_official_quoted_person_with_other_source_citation_is_not_target_use(self):
  text='UNEP Executive Director highlighted sustainable tourism benefits” (IUCN, 2004, p. 14).'
  class Reviewer:
   cfg=True
   def request(self,stage,prompt,payload,validate):
    result={'uses':[{'block_id':'p2:b1','reference_id':'r','quote':'UNEP Executive Director highlighted sustainable tourism benefits”',
                     'reason':'The person represents UNEP'}]}
    validate(result);return {'status':'completed','result':result,'fingerprint':'fixture'}
  idx={'document_id':'doc','references':[{'id':'r','reference_id':'r','raw_citation':'UNEP. 2004. Report.',
       'semantic_review':{'role':'author','boundary':'clean'}}],'contexts':[],'occurrences':[]}
  pages=[{'page':2,'lines':[{'text':text,'block_id':1,'bbox':[0,0,200,12]}]}]
  self.assertEqual(recover(idx,pages,{'canonical_name':'UNEP','aliases':['UNEP']},Reviewer()),[])
  self.assertEqual(idx['occurrences'],[])
