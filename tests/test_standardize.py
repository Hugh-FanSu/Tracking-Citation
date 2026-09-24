import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/paper_citation_pipeline/engine/runtime'))
from standardize_citations import normalize, unep_rows, ORG_YEAR, org_reference


def sample(text, refs, mentions=(), groups=()):
    return {'source': {'sha256': 'test', 'pdf': 'test.pdf'}, 'bibliography': refs,
            'paragraphs': [{'id': 'p1', 'text': text, 'kind': 'p', 'section_id': None, 'coordinates': []}],
            'sections': [], 'citation_mentions': list(mentions), 'pdf_citation_groups': list(groups)}


def ref(i, raw, year='2021'):
    return {'id': i, 'raw_citation': raw, 'year': year, 'title': raw}


class StandardizeTests(unittest.TestCase):
    def test_aliases_preserve_original_and_match_across_forms(self):
        for alias in ['united nations environment', 'UNITED NATIONS ENVIRONMENT PROGRAMME',
                      'United Nations\nEnvironment Programme', 'UN Environment', 'U.N.E.P.']:
            with self.subTest(alias=alias):
                d = sample(f'({alias}, 2021)', [ref('b0', 'United Nations Environment Programme. (2021). Report.')])
                rows = unep_rows(normalize(d, 'paper'))
                self.assertEqual(len(rows), 1)
                self.assertIn(alias, rows[0]['raw_marker'])
                self.assertEqual(rows[0]['organization_id'], 'UNEP')
                identity = org_reference(ref('b1', f'{alias}, 2021. Report.'))
                self.assertEqual(identity['matched_alias_raw'], alias)

    def test_broad_names_are_not_global_aliases(self):
        for name in ['United Nations', 'UN', 'Environment Programme', 'UNEPish', 'United Nations Environment Agency']:
            self.assertIsNone(org_reference(ref('b0', f'{name}, 2021. Report.')))

    def test_repeated_same_paragraph(self):
        d = sample('(UNEP, 2021). Again (UNEP, 2021).', [ref('b0', 'UNEP, 2021. Report.')])
        rows = unep_rows(normalize(d, 'paper'))
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0]['location_id'], rows[1]['location_id'])
        self.assertEqual(rows, unep_rows(normalize(d, 'paper')))

    def test_same_group_two_reports(self):
        d = sample('(UNEP, 2021; UNEP, 2022)', [ref('b0', 'UNEP, 2021. A.'), ref('b1', 'UNEP, 2022. B.', '2022')])
        rows = unep_rows(normalize(d, 'paper'))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['location_id'], rows[1]['location_id'])
        self.assertNotEqual(rows[0]['record_id'], rows[1]['record_id'])

    def test_year_suffix_and_scope(self):
        d = sample('(United Nations, 2024a); (United Nations, 2024b)',
                   [ref('b0', 'United Nations. (2024a). Population.', '2024'),
                    ref('b1', 'United Nations. (2024b). Food Waste Index. https://www.unep. org/a', 'March 21')])
        rows = unep_rows(normalize(d, 'paper'))
        self.assertEqual(len(rows), 1)
        self.assertIn('2024b', rows[0]['raw_marker'])

    def test_mixed_reference_is_blocked(self):
        raw = 'GlobalABC/UNEP. (2022). Buildings report. UNEP. Smith, A. (2007). Other paper.'
        self.assertTrue(org_reference(ref('b0', raw, '2007'))['mixed_reference'])
        d = sample('(GlobalABC/UNEP, 2022)', [ref('b0', raw, '2007')])
        self.assertEqual(unep_rows(normalize(d, 'paper'))[0]['link_status'], 'needs_reference_split')

    def test_report_title_is_not_second_citation(self):
        self.assertIsNone(ORG_YEAR.search('According to UNEP 2024 Food Waste Index Report [22]'))
        self.assertIsNotNone(ORG_YEAR.search('United Nations Environment Programme (2019)'))

    def test_numeric_group_multiple_edges(self):
        refs = [ref('b9', 'UNEP, 2021. Report.'), ref('b10', 'Smith, 2021. A.'), ref('b11', 'UNEP, 2022. B.', '2022')]
        group = {'id': 'g1', 'raw_marker': '[9–11]', 'source': 'original_pdf_characters', 'page': 1,
                 'bboxes': [[1, 2, 3, 4]], 'origin': 'top-left', 'unit': 'PDF point', 'expanded_numbers': [9, 10, 11],
                 'numeric_targets': [{'number': n, 'target_ids': [f'b{n}']} for n in [9, 10, 11]],
                 'citation_ids': [], 'unresolved_numbers': []}
        rows = unep_rows(normalize(sample('[9–11]', refs, groups=[group]), 'paper'))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['location_id'], rows[1]['location_id'])
        self.assertEqual(rows[0]['raw_marker'], '[9–11]')


if __name__ == '__main__':
    unittest.main()
