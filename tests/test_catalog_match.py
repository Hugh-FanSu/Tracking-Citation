import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'src/paper_citation_pipeline/engine/runtime'))
from match_report_catalog import match_reference


def row(title, raw=None):
    return {'parsed_title_unverified':title,'year_label_from_raw':'2022',
            'pdf_review':{'reference_text_after_review':raw or title,'reference_correction_status':'original_entry_retained'}}


def item(title,url='https://www.unep.org/a',date='2022'):
    return {'title':title,'url':url,'date':date,'excel_row':2,'category':'PUBLICATION'}


class CatalogTests(unittest.TestCase):
    def test_edition_title_wins_over_generic(self):
        title='Global Status Report for Buildings and Construction 2022'
        result=match_reference(row(title),[item('Global Status Report for Buildings and Construction'),item('2022 Global Status Report for Buildings and Construction','https://www.unep.org/b')])
        self.assertEqual(result['matched_url'],'https://www.unep.org/b')

    def test_same_title_multiple_urls_still_matches_name(self):
        result=match_reference(row('Marine Litter: A Global Challenge'),[item('Marine Litter: A Global Challenge'),item('Marine litter: a global challenge','https://www.unep.org/b')])
        self.assertEqual(result['status'],'已匹配')
        self.assertIsNone(result['matched_url'])
        self.assertEqual(len(result['catalog_rows']),2)

    def test_url_date_difference_retains_match_and_warning(self):
        result=match_reference(row('A', 'UNEP. 2022. A. https://www.unep.org/a.'),[item('A',date='2014')])
        self.assertEqual(result['status'],'已匹配')
        self.assertTrue(result['notes'])

    def test_unknown_title_not_forced(self):
        self.assertEqual(match_reference(row('Unknown resource'),[item('Different resource')])['status'],'未匹配')

    def test_url_prefix_not_exact_match(self):
        result=match_reference(row('Unknown','https://www.unep.org/a-0'),[item('Different')])
        self.assertEqual(result['status'],'未匹配')
