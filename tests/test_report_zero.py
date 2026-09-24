import unittest
import test_tool
from paper_citation_pipeline.excel import collect

class ReportNameTests(unittest.TestCase):
    setUp=test_tool.ToolTests.setUp
    tearDown=test_tool.ToolTests.tearDown
    write=test_tool.ToolTests.write
    packet=test_tool.ToolTests.packet
    def test_unmatched_name_is_numeric_zero_without_dropping_citation(self):
        for status in ['unmatched','ambiguous','not_searched','blocked_reference']:
            d=self.packet();d['target_candidates'][0]['parsed_title_unverified']='Unverified title'
            d['target_candidates'][0]['report_match']={'status':status}
            rows=collect([self.write('p.json',d)],self.state)['citations']
            self.assertEqual(len(rows),1);self.assertEqual(rows[0]['report_title'],0)
            self.assertIsInstance(rows[0]['report_title'],int)
            self.assertEqual(rows[0]['raw_reference'],'WHO, 2020. Report.')
    def test_matched_name_is_retained(self):
        d=self.packet();d['target_candidates'][0]['report_match']={'status':'matched','matched_title':'Verified title'}
        self.assertEqual(collect([self.write('p.json',d)],self.state)['citations'][0]['report_title'],'Verified title')
