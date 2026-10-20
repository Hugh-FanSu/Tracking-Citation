import copy
import unittest
from paper_citation_pipeline.review_status import export_status, fingerprint, model_evidence_current
from paper_citation_pipeline.delivery import seal


class ReviewStatusTests(unittest.TestCase):
    def setUp(self):
        self.row = dict(record_id='e', report_candidate_id='r', location_id='l',
                        raw_marker='(UNEP, 2020)', raw_reference='UNEP (2020). Report.',
                        paragraph_text='Evidence (UNEP, 2020).', carrier='p', link_status='machine_linked')
        self.packet = dict(source={'sha256': 'a'*64}, target={'canonical_name': 'UNEP'},
                           target_candidates=[self.row], pdf_pages=[dict(page=1, lines=[dict(text=self.row['paragraph_text'], bbox=[0,0,20,20])])])

    def manual(self):
        self.row['record_review'] = dict(fingerprint=fingerprint(self.packet, self.row),
            decision='confirmed', reviewer='Codex', reason='逐字引用与署名支持内容使用。',
            context_status='pending', evidence=[dict(field='raw_reference', quote='UNEP (2020)')])

    def test_default_is_not_confirmation(self):
        self.assertEqual(export_status(self.packet, self.row)['confirmation_status'], '待核实')

    def test_record_confirmation_does_not_confirm_context_or_paper(self):
        self.manual()
        self.packet['local_verification'] = {'status': 'blocked'}
        result = export_status(self.packet, self.row)
        self.assertEqual(result['confirmation_status'], '已确认')
        self.assertEqual(result['context_status'], '需人工复查')
        self.assertEqual(self.packet['local_verification']['status'], 'blocked')

    def test_changed_marker_reference_paragraph_or_pdf_invalidates(self):
        self.manual()
        for field in ('raw_marker', 'raw_reference', 'paragraph_text', 'link_status'):
            with self.subTest(field=field):
                row = copy.deepcopy(self.row); row[field] = 'changed'
                self.assertEqual(export_status(self.packet, row)['confirmation_status'], '待核实')
        self.packet['source']['sha256'] = 'b'*64
        self.assertEqual(export_status(self.packet, self.row)['confirmation_status'], '待核实')

    def test_invented_evidence_cannot_confirm(self):
        self.manual(); self.row['record_review']['evidence'][0]['quote'] = 'invented'
        self.assertEqual(export_status(self.packet, self.row)['confirmation_status'], '待核实')

    def test_explicit_exclusion_and_incomplete_context(self):
        self.manual(); self.row['record_review'].update(decision='excluded', context_status='incomplete')
        result = export_status(self.packet, self.row)
        self.assertEqual(result['confirmation_status'], '排除')
        self.assertEqual(result['context_status'], '上下文仍不完整')

    def test_model_record_can_pass_while_whole_paper_is_blocked(self):
        d=dict(role='author',boundary='clean',evidence='UNEP',author_names=['UNEP'],title='Report',year='2020',reason='signed')
        self.packet['local_verification']=dict(status='blocked',references={'decisions':{'r':d}},
            contexts={'e':dict(status='completed',result=dict(status='complete',relevant=True,
                segments=[dict(start_line='p1:l0',end_line='p1:l0',start=0,end=None)]))})
        seal(self.packet)
        self.assertTrue(model_evidence_current(self.packet))
        result=export_status(self.packet,self.row,model_current=model_evidence_current(self.packet))
        self.assertEqual(result['confirmation_status'],'已确认')
        self.assertEqual(result['context_status'],'上下文完整')
        self.row['paragraph_text']+=' Changed.'
        self.assertFalse(model_evidence_current(self.packet))
        self.assertEqual(export_status(self.packet,self.row,model_current=model_evidence_current(self.packet))['confirmation_status'],'待核实')

    def test_missing_reference_decision_keeps_pending(self):
        self.packet['local_verification']={'status':'passed'};seal(self.packet)
        self.assertEqual(export_status(self.packet,self.row,model_current=True)['confirmation_status'],'待核实')


if __name__ == '__main__':
    unittest.main()
