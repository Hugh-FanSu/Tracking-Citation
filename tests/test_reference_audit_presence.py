import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/paper_citation_pipeline/engine/runtime'))
from docling_bibliography import existing_at_verified_location, same_identifying_text
import test_docling_bibliography as fixtures
from reference_repairs import repair


class PresenceMatchingTests(unittest.TestCase):
    def setUp(self):
        self.raw = 'United Nations Environment Programme, Towards Zero Waste - A Catalyst for Delivering the Sustainable Development Goals (2023). https://unep.org/report.'
        self.loc = {'page': 2, 'x': 40, 'y': 100, 'width': 400, 'height': 10}
        self.reference = {'id': 'b1', 'raw_citation': self.raw, 'coordinates': [self.loc]}

    def present(self, raw=None, coords=None, evidence=None, bibliography=None):
        return existing_at_verified_location(bibliography or [self.reference], raw or self.raw,
            coords or [self.loc], evidence or [self.raw])

    def test_typo_is_presence_only_and_preserves_reference(self):
        before = copy.deepcopy(self.reference)
        self.assertEqual(self.present(raw=self.raw.replace('for Delivering', 'or Delivering'))['id'], 'b1')
        self.assertEqual(self.reference, before)

    def test_url_wrapping_and_separate_diacritics(self):
        self.assertTrue(same_identifying_text(self.raw + ' Nações Quênia /plastic-pollution',
                                            self.raw + ' Naç˜oes Quˆenia /plasticpollution'))

    def test_different_location_rejected(self):
        self.assertIsNone(self.present(coords=[dict(self.loc, page=3)]))

    def test_pdf_must_contain_existing_reference(self):
        self.assertIsNone(self.present(evidence=[self.raw.replace('2023', '2024')]))

    def test_different_year_or_material_title_rejected(self):
        self.assertIsNone(self.present(raw=self.raw.replace('2023', '2024')))
        self.assertIsNone(self.present(raw=self.raw.replace('Zero Waste', 'Marine Pollution')))

    def test_ambiguous_existing_references_rejected(self):
        self.assertIsNone(self.present(bibliography=[self.reference, dict(self.reference, id='b2')]))


class PresenceRecoveryBoundaryTests(unittest.TestCase):
    setUp = fixtures.DoclingBibliographyTests.setUp
    tearDown = fixtures.DoclingBibliographyTests.tearDown
    def test_missing_reference_typo_does_not_relax_recovery_proof(self):
        self.data['docling']['document']['texts'][-1]['text'] = self.raw[-1].replace('outlook', 'otlook')
        working, changes = repair(self.pdf, self.data)
        self.assertEqual(len(changes), 1)
        self.assertEqual(working['reference_region_audit']['entries'][-1]['reason'], 'original_pdf_text_not_verified')
