import unittest,tempfile
from pathlib import Path
import pymupdf
from test_standardize import sample
from pdf_evidence import evidence_session,open_document,evidence_stats
from match_report_catalog import CatalogIndex,match_reference
from test_catalog_match import row,item

class EvidenceTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'a.pdf'
  doc=pymupdf.open();p=doc.new_page();p.insert_text((40,100),'First evidence line.');p.insert_text((40,200),'Second evidence line.');doc.save(self.path);doc.close()
 def tearDown(self):self.temp.cleanup()
 def test_reuse_isolated_mutable_extractions(self):
  with evidence_session() as state:
   with open_document(self.path) as d:
    first=d[0].get_text('dict');first['blocks'].clear()
   with open_document(self.path) as d:
    self.assertTrue(d[0].get_text('dict')['blocks']);self.assertEqual(d[0].get_text(),d[0].get_text())
   self.assertEqual(state.stats['pdf_opens'],1);self.assertEqual(state.stats['native_text_extractions'],2);self.assertEqual(state.stats['text_cache_hits'],2)
  self.assertFalse(state.docs);self.assertFalse(state.cache)
 def test_clipped_text_remains_native(self):
  clip=pymupdf.Rect(0,80,300,120)
  with pymupdf.open(self.path) as d:expected=d[0].get_text(clip=clip)
  with evidence_session() as state,open_document(self.path) as d:
   self.assertEqual(d[0].get_text(clip=clip),expected);self.assertEqual(d[0].get_text(clip=clip),expected)
   self.assertEqual(state.stats['text_cache_hits'],0)
 def test_cleanup_after_exception_and_fresh_file(self):
  with self.assertRaises(ValueError):
   with evidence_session() as state,open_document(self.path) as d:
    d[0].get_text();raise ValueError('stop')
  self.assertIsNone(evidence_stats());self.assertFalse(state.docs)
  self.path.unlink();doc=pymupdf.open();p=doc.new_page();p.insert_text((40,100),'Replacement evidence.');doc.save(self.path);doc.close()
  with evidence_session(),open_document(self.path) as d:self.assertIn('Replacement',d[0].get_text())
 def test_memory_budget_bypasses_oversized_results(self):
  with evidence_session(max_cache_bytes=100) as state,open_document(self.path) as d:
   d[0].get_text('dict');d[0].get_text('dict');self.assertEqual(state.stats['text_cache_hits'],0);self.assertLessEqual(state.bytes,100)
 def test_cached_and_native_formats_and_order_agree(self):
  with pymupdf.open(self.path) as d:expected={(fmt,sort):d[0].get_text(fmt,sort=sort) for fmt in ['text','dict','rawdict','blocks'] for sort in [False,True]}
  with evidence_session(),open_document(self.path) as d:
   for key,value in expected.items():
    self.assertEqual(d[0].get_text(key[0],sort=key[1]),value);self.assertEqual(d[0].get_text(key[0],sort=key[1]),value)
 def test_catalog_index_preserves_ambiguity_year_and_urls(self):
  rows=[item('Marine Litter: A Global Challenge'),item('Marine litter: a global challenge','https://www.unep.org/b',date='2014')];index=CatalogIndex(rows)
  for value in [row('Marine Litter: A Global Challenge'),row('Unknown','https://www.unep.org/b.'),row('Unknown','https://www.unep.org/a-0')]:self.assertEqual(match_reference(value,rows),match_reference(value,index))
