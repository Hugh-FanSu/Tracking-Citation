import copy
import tempfile
import unittest
from pathlib import Path
import pymupdf
from test_standardize import sample,ref
from standardize_citations import normalize,org_reference,unep_rows
from reference_repairs import local_metadata
from footnote_sources import recover as footnotes
from bracket_ranges import recover as ranges
from target_recovery import coord

class Publisher084Tests(unittest.TestCase):
 def test_quoted_title_publisher_is_not_institutional_authorship(self):
  r=ref('a','C. Montes, "Screening for critical habitat," UNEP-WCMC, 2017.','2017');r['authors']=[dict(family='Montes')]
  identity=org_reference(r)
  self.assertIn('target_in_explicit_post_title_publisher_field',identity['evidence']);self.assertIsNone(identity['joint_authorship'])
 def test_title_mention_and_funding_not_publisher(self):
  for raw in ['Smith, "UNEP-WCMC programmes," Nature, 2017.','Smith, "Habitat," funded by UNEP-WCMC, 2017.']:
   r=ref('a',raw,'2017');r['authors']=[dict(family='Smith')]
   self.assertIsNone(org_reference(r))
 def test_explicit_place_publisher_is_retained(self):
  r=org_reference(ref('a','CBD (1992) Convention on biological diversity (Nairobi: UNEP).','1992'))
  self.assertIn('target_in_place_publisher_field',r['evidence'])
 def test_split_metadata_only_belongs_to_supported_child(self):
  parent=dict(identifiers=[dict(type='DOI',value='10.1016/0016-7061(94)00062-F')],authors=[dict(family='Fendorf')],venue='Geoderma')
  a=local_metadata(parent,'FAO and UNEP: Global assessment of soil pollution, 2021.','FAO and UNEP')
  self.assertEqual(a,dict(identifiers=[],authors=[],venue=None))
  b=local_metadata(parent,'Fendorf: Surface reactions. Geoderma. https://doi.org/10.1016/0016-7061(94)00062-F','Fendorf')
  self.assertEqual(b,parent)
 def make_footnotes(self,path,pointer=29,author='UNEP',body=True):
  doc=pymupdf.open();p=doc.new_page()
  for y in [100,120,140]:p.insert_text((50,y),'A detailed discussion of climate risks and future temperature goals.',fontsize=12)
  if body:
   p.insert_text((50,200),'This finding is supported by the report.',fontsize=12);p.insert_text((50+pymupdf.get_text_length('This finding is supported by the report.',fontsize=12),196),'31',fontsize=6)
   p.insert_text((50,230),'The projected warming exceeds the goal.',fontsize=12);p.insert_text((50+pymupdf.get_text_length('The projected warming exceeds the goal.',fontsize=12),226),'32',fontsize=6)
  for y,n,text in [(600,29,'IPCC, Climate Change (2021).'),(620,31,'UNEP, Emissions Gap Report (2020).'),(640,32,f'{author}, supra note {pointer}, at xxi.')]:
   p.insert_text((50,y),str(n),fontsize=4);p.insert_text((57,y),text,fontsize=8)
  doc.save(path);doc.close()
 def test_supra_conflict_keeps_use_but_not_report_name(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'a.pdf';self.make_footnotes(p);idx=normalize(sample('',[]),'p');changes,findings=footnotes(p,idx)
   self.assertEqual(len(changes),2);self.assertEqual(findings[0]['code'],'footnote_cross_reference_conflict')
   rows=unep_rows(idx);self.assertEqual({r['raw_marker'] for r in rows},{'31','32'});self.assertIsNone(next(r for r in rows if r['raw_marker']=='32')['parsed_title_unverified'])
   self.assertEqual(footnotes(p,idx)[0],[])
 def test_valid_supra_uses_explicit_number(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'a.pdf';self.make_footnotes(p,pointer=31);idx=normalize(sample('',[]),'p');changes,findings=footnotes(p,idx)
   self.assertEqual(len(changes),2);self.assertEqual(findings,[])
   self.assertEqual({r['raw_reference'] for r in unep_rows(idx)},{'UNEP, Emissions Gap Report (2020).'})
 def test_reference_without_body_callout_not_counted(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'a.pdf';self.make_footnotes(p,body=False);idx=normalize(sample('',[]),'p');self.assertEqual(footnotes(p,idx)[0],[])
 def test_other_author_supra_not_assumed_target(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'a.pdf';self.make_footnotes(p,author='Smith');idx=normalize(sample('',[]),'p');self.assertEqual(len(footnotes(p,idx)[0]),1)
 def test_bracket_range_requires_existing_marker_anchor(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'a.pdf';doc=pymupdf.open();pg=doc.new_page();pg.insert_text((40,100),'Prior work [15]-[17] supports the result.');box=pg.search_for('[17]')[0];doc.save(p);doc.close()
   data=sample('',[]);data['pdf_citation_groups']=[];self.assertEqual(ranges(p,data),[])
   data['citation_mentions']=[dict(id='m',style='numeric',expanded_numbers=[17],coordinates=[coord(1,box)],numeric_targets=[dict(number=17,target_id='b17')])]
   data['pdf_citation_groups']=[dict(id='old',citation_ids=['m'])];changes=ranges(p,data)
   self.assertEqual(changes[0]['expanded_numbers'],[15,16,17]);self.assertEqual(len(data['pdf_citation_groups']),1);self.assertEqual(data['pdf_citation_groups'][0]['raw_marker'],'[15]-[17]')
   data['pdf_citation_groups'][0]['citation_validity']='mathematical_set_membership_interval';self.assertEqual(ranges(p,data),[]);self.assertEqual(data['pdf_citation_groups'][0]['citation_validity'],'mathematical_set_membership_interval')
 def test_reference_interleaved_with_publisher_note_needs_pdf_anchor(self):
  from docling_bibliography import recover
  for anchored in [True,False]:
   with self.subTest(anchored=anchored),tempfile.TemporaryDirectory() as t:
    p=Path(t)/'a.pdf';doc=pymupdf.open();page=doc.new_page();raw='UNEP (2020). Emissions Gap Report.';page.insert_text((40,150),raw);box=page.search_for(raw)[0];doc.save(p);doc.close()
    refs=[ref('b','Smith (2019). A detailed independent study of atmospheric chemistry and environmental policy. '+raw,'2019')] if anchored else []
    if refs:refs[0]['coordinates']=[coord(1,box)]
    data=sample('',refs);texts=[dict(self_ref='#/texts/0',label='section_header',text='References'),dict(self_ref='#/texts/1',label='section_header',text="Publisher's note"),dict(self_ref='#/texts/2',label='text',text=raw,prov=[dict(page_no=1,bbox=dict(l=box.x0,t=box.y0,r=box.x1,b=box.y1,coord_origin='TOPLEFT'))])]
    data['docling']=dict(document=dict(texts=texts,body=dict(children=[{'$ref':x['self_ref']} for x in texts])))
    changes=recover(p,data);self.assertEqual(len(changes),int(anchored))
 def test_corrupted_tei_marker_repaired_without_changing_years(self):
  from marker_evidence import repair_nested_author_marker
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'a.pdf';doc=pymupdf.open();page=doc.new_page();page.insert_text((40,100),'Claim (CBD 1992, 2007).');box=page.search_for('(CBD 1992, 2007)')[0];doc.save(p);doc.close()
   idx=normalize(sample('',[ref('b','UNEP (1992). Report.','1992')]),'p');rid=idx['references'][0]['reference_id']
   o=dict(location_id='loc',raw_marker='(CBD 1992(CBD , 2007))',coordinates=[coord(1,box)],marker_source='grobid_tei',offsets=dict(start=0,end=22),links=[dict(reference_id=rid)])
   idx['occurrences']=[o];self.assertEqual(len(repair_nested_author_marker(p,idx)),1);self.assertEqual(o['raw_marker'],'(CBD 1992, 2007)')
   o['raw_marker']='(CBD 1992(CBD , 2008))';self.assertEqual(repair_nested_author_marker(p,idx),[])
 def test_issue_year_wins_over_different_copyright_year(self):
  from metadata_repair import repair_metadata
  for header,y in [('2025, Vol. 43(1) 121-132',40),('EJIL (2025), Vol. 33 No. 3, 925-951',790)]:
   with self.subTest(header=header),tempfile.TemporaryDirectory() as t:
    p=Path(t)/'a.pdf';doc=pymupdf.open();page=doc.new_page();page.insert_text((40,y),header);page.insert_text((40,810),'© 2024');doc.save(p);doc.close()
    meta,_=repair_metadata(p,dict(title='Paper',authors=[],abstract='A summary'));self.assertEqual(meta['year'],2025)
 def test_footnote_already_linked_with_bbox_not_duplicated(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'a.pdf';self.make_footnotes(p);idx=normalize(sample('',[]),'p');footnotes(p,idx)
   for o in idx['occurrences']:
    o['location_id']='existing_'+o['location_id']
    o['coordinates']=[dict(page=c['page'],bbox=[c['x'],c['y'],c['x']+c['width'],c['y']+c['height']]) for c in o['coordinates']]
   self.assertEqual(footnotes(p,idx)[0],[]);self.assertEqual(len(unep_rows(idx)),2)
