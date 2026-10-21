import unittest
from paper_citation_pipeline.reference_regions import is_reference_heading, select_region, overlapping_windows


class ReferenceRegionsTests(unittest.TestCase):
    def test_heading_noise_and_non_headings(self):
        for text in ['`References', '17. REFERENCES:', '• Bibliography', 'References and notes', 'BIBLIOGRAPHIC REFERENCES']:
            self.assertTrue(is_reference_heading(text), text)
        for text in ['See references below.', 'References support this claim', '']:
            self.assertFalse(is_reference_heading(text), text)

    def test_heading_recovers_pages_missing_from_parser(self):
        lines=[dict(id=f'p{p}',page=p,text='`References' if p==17 else 'Entry') for p in range(1,21)]
        selected, coverage=select_region(lines,[dict(coordinates=[dict(page=18),dict(page=19)])],20)
        self.assertEqual(coverage['pages'],[17,18,19,20])
        self.assertEqual(len(selected),4)
        self.assertTrue(coverage['independently_located'])

    def test_no_parser_and_no_heading_cannot_certify_coverage(self):
        lines=[dict(id='l',page=10,text='An entry')]
        _,coverage=select_region(lines,[],10)
        self.assertFalse(coverage['independently_located'])
        self.assertIn(10,coverage['pages'])

    def test_native_heading_excludes_earlier_parser_body_anchors(self):
        lines=[dict(id='body',page=7,text='Towards a Green Economy (UNEP, 2011)',bbox=[50,700,300,712]),
               dict(id='pre_heading',page=13,text='Body paragraph',bbox=[50,200,300,212]),
               dict(id='heading',page=13,text='BIBLIOGRAPHIC REFERENCES',bbox=[50,600,267,625]),
               dict(id='left_ref',page=13,text='UNEP. 2011. Report.',bbox=[50,640,300,652]),
               dict(id='right_ref',page=13,text='Other reference',bbox=[333,160,589,172]),
               dict(id='last_ref',page=14,text='Another reference',bbox=[50,100,300,112])]
        selected,coverage=select_region(lines,[dict(coordinates=[dict(page=7),dict(page=13)])],14)
        self.assertEqual(coverage['pages'],[13,14])
        self.assertEqual([line['id'] for line in selected],['heading','left_ref','right_ref','last_ref'])

    def test_windows_cover_every_core_line_and_overlap(self):
        lines=[dict(id=str(n),text='entry line') for n in range(133)]
        windows=list(overlapping_windows(lines))
        self.assertEqual([i for _,core in windows for i in core],[l['id'] for l in lines])
        self.assertIn('60',[l['id'] for l in windows[0][0]])
        self.assertIn('59',[l['id'] for l in windows[1][0]])
        self.assertEqual(windows[-1][1][-1],'132')
