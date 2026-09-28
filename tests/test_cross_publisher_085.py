import tempfile
import unittest
from pathlib import Path
import pymupdf
from test_standardize import sample,ref
from standardize_citations import normalize,unep_rows,org_reference
from footnote_sources import recover,read_notes
from docling_bibliography import recover as bibliography
from metadata_repair import repair_metadata
from target_recovery import coord

class Publisher085Tests(unittest.TestCase):
 def fixture(self,path,notes,second_page=False):
  doc=pymupdf.open()
  for items in notes:
   p=doc.new_page()
   for y in range(60,310,20):p.insert_text((45,y),'The main text discusses the evidence and implications of this important finding.',fontsize=12)
   for j,(n,text) in enumerate(items):
    p.insert_text((45,340+j*20),'The evidence supports this finding.',fontsize=12)
    p.insert_text((45+pymupdf.get_text_length('The evidence supports this finding.',fontsize=12),336+j*20),str(n),fontsize=6)
    # Numbers in the same span, and separately drawn at the same font size.
    if j%2:p.insert_text((45,600+j*20),f'{n}  '+text,fontsize=8)
    else:
     p.insert_text((45,600+j*20),str(n)+'  ',fontsize=8);p.insert_text((60,600+j*20),text,fontsize=8)
  doc.save(path);doc.close()
 def test_plain_numbers_above_n_and_bare_pinpoint(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'a.pdf';self.fixture(p,[[(1,'UNEP, Climate Litigation Report (Nairobi, 2020).'),(2,'At 4.')],[(3,'For a definition see generally UNEP, above n 1.'),(4,'At 22-23.'),(12,'UNEP, above n 1, at 25.')]])
   idx=normalize(sample('',[]),'p');changes,findings=recover(p,idx)
   self.assertEqual(findings,[]);self.assertEqual(len(changes),5)
   rows=unep_rows(idx);self.assertEqual({r['raw_marker'] for r in rows},{'1','2','3','4','12'})
   self.assertEqual({r['parsed_title_unverified'] for r in rows},{'Climate Litigation Report'})
   self.assertTrue(all(r['citation_sentence'] for r in rows))
   self.assertTrue(all(r['sentence_status']=='original_pdf_sentence_boundary_heuristic' for r in rows))
   self.assertEqual(recover(p,idx)[0],[])
 def test_bare_pinpoint_cannot_cross_page(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'a.pdf';self.fixture(p,[[(1,'Smith, Other Report (2019).'),(2,'UNEP, Climate Report (2020).')],[(3,'At 4.'),(4,'Smith, Other Report (2018).')]])
   idx=normalize(sample('',[]),'p');recover(p,idx);self.assertEqual([r['raw_marker'] for r in unep_rows(idx)],['2'])
 def test_bare_pinpoint_after_mixed_note_is_not_guessed(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'a.pdf';self.fixture(p,[[(1,'UNEP, Climate Report (2020); Smith, Other Report (2019).'),(2,'At 4.')]])
   idx=normalize(sample('',[]),'p');recover(p,idx);self.assertEqual([r['raw_marker'] for r in unep_rows(idx)],['1'])
 def test_ambiguous_repeated_number_is_not_resolved(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'a.pdf';self.fixture(p,[[(1,'UNEP, First Report (2020).'),(2,'Smith, Other Report (2019).')],[(1,'UNEP, Second Report (2021).'),(3,'UNEP, above n 1, at 2.')]])
   idx=normalize(sample('',[]),'p');_,findings=recover(p,idx)
   self.assertEqual(findings[0]['code'],'footnote_cross_reference_conflict')
   self.assertIsNone(next(r for r in unep_rows(idx) if r['raw_marker']=='3')['parsed_title_unverified'])
 def test_expanded_joint_authorship_and_title_false_positive(self):
  r=org_reference(ref('a','United Nations Environment Programme and International Livestock Research Institute. Preventing the Next Pandemic. 2020.','2020'))
  self.assertEqual(len(r['joint_authorship']['coauthors']),2)
  for text in ['UNEP and climate change. A critical account. 2020.','UNEP and International Research Report. 2020.']:
   self.assertIsNone((org_reference(ref('a',text,'2020')) or {}).get('joint_authorship'))
 def test_fused_printed_number_and_author_only_title(self):
  with tempfile.TemporaryDirectory() as t:
   path=Path(t)/'a.pdf';doc=pymupdf.open();pg=doc.new_page();raw='United Nations Environment Programme. Emissions Gap Report 2020. UNEP, 2020.'
   pg.insert_text((40,120),'21. '+raw,fontsize=10);box=pg.search_for('21. '+raw)[0];doc.save(path);doc.close()
   data=sample('',[dict(ref('b',raw,'2020'),title='United Nations Environment Programme',coordinates=[coord(1,box)])])
   texts=[dict(self_ref='#/texts/0',label='section_header',text='References'),dict(self_ref='#/texts/1',label='list_item',text='21.'+raw,prov=[dict(page_no=1,bbox=dict(l=box.x0,t=box.y0,r=box.x1,b=box.y1,coord_origin='TOPLEFT'))])]
   data['docling']=dict(document=dict(texts=texts,body=dict(children=[{'$ref':x['self_ref']} for x in texts])))
   changes=bibliography(path,data);self.assertEqual(data['reference_region_audit']['entries'][0]['status'],'present');self.assertEqual(data['bibliography'][0]['title'],'Emissions Gap Report 2020')
   self.assertEqual(changes[0]['kind'],'repair_author_only_reference_title')
 def test_repeated_issue_header_not_submission_year(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'a.pdf';doc=pymupdf.open();pg=doc.new_page();pg.insert_text((40,700),'Submitted for a degree, 2021.')
   for i in range(2):pg=doc.new_page();pg.insert_text((40,40),'(2022) 53 VUWLR')
   doc.save(p);doc.close();meta,_=repair_metadata(p,dict(title='Paper',authors=[],abstract='Summary'));self.assertEqual(meta['year'],2022)
 def test_cross_page_body_context_excludes_acknowledgment_and_header(self):
  from footnote_sources import note_context
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'a.pdf';doc=pymupdf.open();a=doc.new_page()
   a.insert_text((45,300),'Of the various legal causes of action currently being',fontsize=12)
   a.insert_text((45,550),'* Submitted for the degree, with acknowledgments to the supervisor.',fontsize=8)
   for y,n in [(600,1),(620,2)]:
    a.insert_text((45,y),str(n)+'  ',fontsize=8);a.insert_text((60,y),'UNEP, Climate Report (2020).',fontsize=8)
   b=doc.new_page();b.insert_text((45,40),'(2022) 53 VUWLR',fontsize=8)
   b.insert_text((45,100),'deployed by plaintiffs, the evidence supports this conclusion.',fontsize=12)
   for y,n in [(600,3),(620,4)]:
    b.insert_text((45,y),str(n)+'  ',fontsize=8);b.insert_text((60,y),'UNEP, above n 1.',fontsize=8)
   doc.save(p);doc.close()
   with pymupdf.open(p) as doc:
    pages=[read_notes(pg) for pg in doc];idx=normalize(sample('',[]),'p')
    blocks=[next(b for b in pg.get_text('dict')['blocks'] if b.get('lines') and any('causes of action' in v['text'] or 'deployed by' in v['text'] for l in b['lines'] for v in l['spans'])) for pg in doc]
    ids=[note_context(doc,pages,idx,n+1,b,b['lines'][0]['spans'][0])[0] for n,b in enumerate(blocks)]
    self.assertEqual(ids[0],ids[1]);ctx=next(c for c in idx['contexts'] if c['id']==ids[0]);self.assertIn('deployed by',ctx['text']);self.assertNotIn('Submitted',ctx['text']);self.assertNotIn('VUWLR',ctx['text']);self.assertEqual(len(ctx['coordinates']),2)
