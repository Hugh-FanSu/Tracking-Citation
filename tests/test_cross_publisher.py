import tempfile
from pathlib import Path
import unittest
import pymupdf
from test_standardize import sample,ref
from standardize_citations import normalize,org_reference,unep_rows
from explicit_attribution import recover
from docling_bibliography import recover as recover_refs

class CrossPublisherTests(unittest.TestCase):
 def test_compact_joint_signature_before_title_and_trailing_date(self):
  for signature in ['UNEP-WCMC & IUCN','IUCN & UNEP-WCMC','UNEP & FAO']:
   r=org_reference(ref('r',signature+'. A dataset title. Protected Planet (2025).','2025'))
   self.assertIsNotNone(r['joint_authorship']);self.assertIn('target_in_joint_authorship',r['evidence'])
 def test_ambiguous_compound_signature_enters_author_review(self):
  r=org_reference(ref('r','UNEP-OtherUnit & Partner. Data (2025).','2025'))
  self.assertEqual(r['identity_status'],'candidate_related_organization_scope')
 def test_decorated_heading_and_numbered_trailing_year(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'p.pdf';doc=pymupdf.open();pg=doc.new_page();raw='UNEP Methane emissions report; UNEP, 2021.';pg.insert_text((45,100),'(6) '+raw);box=pg.search_for('(6) '+raw)[0];doc.save(p);doc.close()
   data=sample('',[]);data['docling']={'document':{'texts':[
    {'self_ref':'#/texts/0','label':'section_header','text':'■ REFERENCES'},
    {'self_ref':'#/texts/1','label':'list_item','text':raw,'marker':'(6)','prov':[{'page_no':1,'bbox':dict(l=box.x0,t=box.y0,r=box.x1,b=box.y1,coord_origin='TOPLEFT')}]}],
    'body':{'children':[{'$ref':'#/texts/0'},{'$ref':'#/texts/1'}]}}}
   changes=recover_refs(p,data)
   self.assertEqual(len(changes),1);self.assertEqual(data['bibliography'][0]['numeric_label'],6)
 def test_explicit_data_use_and_idempotence(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'p.pdf';doc=pymupdf.open();pg=doc.new_page();pg.insert_text((40,100),'We used UNEP seagrass data to train our model.');doc.save(p);doc.close()
   idx=normalize(sample('',[]),'p');self.assertEqual(len(recover(p,idx)),1);self.assertEqual(recover(p,idx),[])
   row=unep_rows(idx)[0];self.assertEqual(row['raw_marker'],'');self.assertEqual(row['citation_form'],'explicit_source_use_without_marker');self.assertIsNone(row['year_label_from_raw'])
 def test_nonuse_affiliation_and_unrelated_sentence_excluded(self):
  for text in ['We did not use UNEP data.', 'UNEP data are available online.', 'Authors: UNEP data team.', 'We used Smith data. UNEP data are discussed elsewhere.']:
   with self.subTest(text=text),tempfile.TemporaryDirectory() as t:
    p=Path(t)/'p.pdf';doc=pymupdf.open();pg=doc.new_page();pg.insert_text((40,100),text);doc.save(p);doc.close()
    self.assertEqual(recover(p,normalize(sample('',[]),'p')),[])
 def test_printed_parenthesis_number_links_existing_superscript(self):
  from target_recovery import recover_numeric,coord
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'p.pdf';doc=pymupdf.open();pg=doc.new_page();raw='UNEP, 2021. Methane emissions report.';pg.insert_text((45,200),'(6) '+raw);box=pg.search_for('(6) '+raw)[0];doc.save(p);doc.close()
   idx=normalize(sample('Claim6',[ref('r',raw,'2021')]),'p');r=idx['references'][0];r['coordinates']=[coord(1,box)]
   idx['occurrences']=[dict(location_id='loc',raw_marker='6',style='numeric',expanded_numbers=[6],unresolved_numbers=[6],links=[])]
   changes,_=recover_numeric(p,{},idx)
   self.assertEqual(len(changes),1);self.assertEqual(idx['occurrences'][0]['links'][0]['reference_id'],r['reference_id'])
   self.assertEqual(recover_numeric(p,{},idx)[0],[])
 def test_formal_target_reference_not_duplicated_by_attribution(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'p.pdf';doc=pymupdf.open();pg=doc.new_page();text='We used UNEP data [1].';pg.insert_text((40,100),text);doc.save(p);doc.close()
   idx=normalize(sample(text,[ref('r','UNEP, 2021. Data report.','2021')]),'p')
   idx['occurrences']=[dict(paragraph_id=idx['contexts'][0]['id'],links=[dict(reference_id=idx['references'][0]['reference_id'])])]
   self.assertEqual(recover(p,idx),[])
 def test_unrelated_website_in_same_sentence_is_not_target_url(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'p.pdf';doc=pymupdf.open();pg=doc.new_page();text='We used UNEP data and Seagrass Spotter https://seagrassspotter.org/.';pg.insert_text((40,100),text,fontsize=9);box=pg.search_for('https://seagrassspotter.org/')[0];pg.insert_link({'kind':pymupdf.LINK_URI,'from':box,'uri':'https://seagrassspotter.org/'})
   doc.save(p);doc.close();idx=normalize(sample('',[]),'p');recover(p,idx);self.assertEqual(unep_rows(idx)[0]['source_urls'],[])

class LocalEvidence082Tests(unittest.TestCase):
 def test_expanded_signature_uses_local_parenthetical_abbreviations(self):
  from standardize_citations import local_author_signature
  raw='UN Environment Programme World Conservation Monitoring Centre (UNEP- WCMC), & International Union for Conservation of Nature (IUCN). (2023). Protected Planet.'
  r=local_author_signature(ref('r',raw,'2023'))
  self.assertIn('UNEP-WCMC',r['coauthors']);self.assertIn('IUCN',r['coauthors'])
  self.assertIsNone(local_author_signature(ref('r','This study was funded by '+raw,'2023')))
 def resource_case(self,text,other=False):
  from local_sources import recover_local_sources
  from target_recovery import coord
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'p.pdf';doc=pymupdf.open();pg=doc.new_page();pg.insert_textbox((40,100,550,250),text,fontsize=10);doc.save(p);doc.close()
   idx=normalize(sample('',[ref('r','UNEP, 2023. World Database on Protected Areas.','2023')]),'p');r=idx['references'][0];r['title']='World Database on Protected Areas';r['coordinates']=[dict(page=1,x=40,y=600,width=200,height=20)]
   if other:
    import copy
    r2=copy.deepcopy(r);r2.update(id='other',reference_id='other',organization_candidate=None);idx['references'].append(r2)
   changes,findings=recover_local_sources(p,idx);self.assertEqual(recover_local_sources(p,idx)[0],[])
   return changes,idx
 def test_local_resource_without_invented_edition(self):
  changes,idx=self.resource_case('Using the World Database of Protected Areas, we estimated coverage.')
  self.assertEqual(len(changes),1);r=idx['references'][-1];self.assertIsNone(r['year']);self.assertEqual(idx['occurrences'][0]['raw_marker'],'')
 def test_resource_nonuse_unrelated_sentence_and_conflicting_authors(self):
  for text in ['We did not use the World Database of Protected Areas.','We used another source. World Database of Protected Areas is available.','World Database of Protected Areas is available.']:
   self.assertEqual(self.resource_case(text)[0],[])
  self.assertEqual(self.resource_case('Using the World Database of Protected Areas, we estimated coverage.',True)[0],[])
 def test_policy_borrowing_is_pending_not_edge(self):
  from local_sources import recover_local_sources
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'p.pdf';doc=pymupdf.open();pg=doc.new_page();pg.insert_textbox((40,100,550,250),'A fund modeled after the Montreal Protocol could subsidize costs.');doc.save(p);doc.close()
   idx=normalize(sample('',[ref('r','UNEP, 2016. Montreal Protocol on Substances.','2016')]),'p');r=idx['references'][0];r['title']='United Nations Environment Programme. Montreal Protocol on Substances';r['coordinates']=[dict(page=1,x=40,y=600,width=200,height=20)]
   changes,findings=recover_local_sources(p,idx);self.assertEqual(changes,[]);self.assertEqual(findings[0]['code'],'policy_source_use_requires_review');self.assertEqual(idx['occurrences'],[])
 def test_metadata_footer_not_submission_year(self):
  from metadata_repair import repair_metadata
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'p.pdf';doc=pymupdf.open();pg=doc.new_page();pg.insert_text((40,40),'Received 2024. Accepted 2025.');pg.insert_text((40,760),'This follows Smith et al., 2007) in practice.');pg.insert_text((40,790),'Journal (2026) 7:585');doc.save(p);doc.close()
   m,_=repair_metadata(p,dict(title='A title',authors=[],abstract='Existing abstract'))
   self.assertEqual(m['year'],2026);self.assertEqual(m['abstract'],'Existing abstract')

class CrossReference083Tests(unittest.TestCase):
 def test_explicit_formula_callout_excluded_without_excluding_square_citation(self):
  from standardize_citations import structural_cross_reference
  for text,marker in [('calculated using formula (7)','(7)'),('see equations (6) and (7)','(7)'),('see Table 7','7')]:
   self.assertTrue(structural_cross_reference(text,text.rfind(marker),marker))
  for text,marker in [('method [7]','[7]'),('as in Smith (7)','(7)'),('The formula used in this study (7)','(7)')]:
   self.assertFalse(structural_cross_reference(text,text.rfind(marker),marker))

class Bibliography083Tests(unittest.TestCase):
 def test_every_url_checked_not_just_first_url(self):
  raw='Smith. Prior item https://doi.org/10.123/a. United Nations. 2024. Outlook. https:// www. unep. org/resources/a.'
  self.assertIn('target_domain_in_reference',org_reference(ref('r',raw,'2024'))['evidence'])
 def test_colon_joint_signature(self):
  r=org_reference(ref('r','FAO and UNEP: Global assessment of soil pollution, Rome, FAO, 2021.','2021'))
  self.assertEqual(r['joint_authorship']['coauthors'],['FAO','UNEP'])
 def test_split_initials_join_uses_local_coordinates(self):
  from docling_bibliography import join_split_reference
  def c(x,y,w=20):return dict(page=1,x=x,y=y,width=w,height=8)
  a=ref('a','Unep, U.',None);a['coordinates']=[c(40,100)]
  b=ref('b','N. E. P. (2022). Fire report.','2022');b['coordinates']=[c(65,100,190)]
  other=ref('other','Unep, U.',None);other['coordinates']=[c(40,200)]
  d=sample('',[a,b,other]);raw='Unep, U. N. E. P. (2022). Fire report.'
  change=join_split_reference(d,dict(text=raw,self_ref='#/texts/1'),[c(40,100,220)],[raw],None)
  self.assertIsNotNone(change);self.assertEqual(change['reference']['year'],'2022');self.assertEqual(change['reference']['title'],'Fire report.')
  self.assertEqual({r['id'] for r in d['bibliography']},{'a','other'})
 def test_locate_marker_keeps_only_original_marker_page(self):
  from marker_evidence import locate
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'p.pdf';doc=pymupdf.open();doc.new_page();pg=doc.new_page();pg.insert_text((40,100),'The method uses (UNEP, 2023).');doc.save(p);doc.close()
   idx=normalize(sample('The method uses (UNEP, 2023).',[ref('r','UNEP, 2023. Report.','2023')]),'p')
   idx['contexts'][0]['coordinates']=[dict(page=n,x=0,y=0,width=595,height=842) for n in [1,2]]
   changes=locate(p,idx);self.assertTrue(changes);self.assertEqual({c['page'] for c in idx['occurrences'][0]['coordinates']},{2})

class Numeric083Tests(unittest.TestCase):
 def test_wrapped_superscript_range_in_two_pdf_blocks(self):
  from superscript_groups import recover as groups
  from target_recovery import coord
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'p.pdf';doc=pymupdf.open();pg=doc.new_page();pg.insert_text((40,100),'A sufficiently long claim',fontsize=11);pg.insert_text((150,97),'5,10-',fontsize=7);pg.insert_text((40,110),'13',fontsize=7);pg.insert_text((52,113),'. Further explanation.',fontsize=11)
   box=pg.search_for('13')[0];doc.save(p);doc.close()
   data=dict(citation_mentions=[dict(id='m',style='numeric',coordinates=[coord(1,box)],expanded_numbers=[13],numeric_targets=[dict(number=13,target_id='r')])])
   found=groups(p,data);self.assertEqual(len(found),1);self.assertEqual(found[0]['raw_marker'],'5,10-13');self.assertEqual(found[0]['expanded_numbers'],[5,10,11,12,13])
 def test_pdf_native_entry_replaces_corrupted_docling_text(self):
  from docling_bibliography import native_numbered_entry
  from target_recovery import coord
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'p.pdf';doc=pymupdf.open();pg=doc.new_page();pg.insert_text((40,100),'(12) UNEP. Global Mercury Supply, Trade and Demand; UNEP,',fontsize=9);pg.insert_text((40,111),'2017.',fontsize=9);pg.insert_text((40,122),'(13) Smith. Another reference.',fontsize=9)
   rect=pg.search_for('(12) UNEP. Global Mercury Supply, Trade and Demand; UNEP,')[0]|pg.search_for('2017.')[0]
   native=native_numbered_entry(doc,[coord(1,rect)]);self.assertIsNotNone(native);self.assertEqual(native[1],'(12)');self.assertNotIn('Smith',native[0]);doc.close()
 def test_expert_group_joint_authorship_is_local(self):
  r=org_reference(ref('r','UNEP/AMAP Expert group. Global Mercury Assessment (2013).','2013'))
  self.assertEqual(r['joint_authorship']['coauthors'],['UNEP','AMAP'])

class Roles083Tests(unittest.TestCase):
 def test_mixed_full_name_and_acronym_joint_signature(self):
  r=org_reference(ref('r','AMAP/UN Environment (2019). Technical report.','2019'))
  self.assertEqual(r['joint_authorship']['coauthors'],['AMAP','UN Environment'])
 def test_bracketed_author_list_does_not_depend_on_report_year_position(self):
  r=org_reference(ref('r','Global Alliance [GlobalABC]; International Energy Agency [IEA]; United Nations Environment Program [UNEP]. GlobalABC Roadmap 2020-2050; IEA, 2020.','2020'))
  self.assertIsNotNone(r['joint_authorship'])

class Metadata083Tests(unittest.TestCase):
 def test_header_publication_date_not_doi_or_acceptance_year(self):
  from metadata_repair import repair_metadata
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'p.pdf';doc=pymupdf.open();pg=doc.new_page();pg.insert_text((40,40),'Journal (2025) 37:11');pg.insert_text((40,60),'https://doi.org/10.123/journal.2024.1');pg.insert_text((40,300),'Accepted: 12 December 2024');doc.save(p);doc.close()
   m,_=repair_metadata(p,dict(title='Title',authors=[],abstract='Abstract'));self.assertEqual(m['year'],2025)
