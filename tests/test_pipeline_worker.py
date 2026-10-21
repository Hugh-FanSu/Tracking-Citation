import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from paper_citation_pipeline.ledger.pipeline_worker import PipelineWorker

class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.client=Mock();self.w=PipelineWorker(self.client,'node',[],self.tmp.name)
        self.w.guard=Mock();self.w.guard.check.return_value=''
    def job(self,ident,stage):
        j={'task':{'id':ident,'paper_id':ident,'lease_token':'lease'},'stage':stage,'work':str(Path(self.tmp.name)/ident)}
        self.w.jobs[ident]=j;return j
    def test_review_and_parse_overlap_without_third_claim(self):
        a=self.job('a','reviewing');b=self.job('b','parsing')
        with patch.object(self.w,'poll'),patch.object(self.w,'launch') as launch:self.w.tick()
        launch.assert_not_called();self.client.post.assert_not_called()
    def test_handoff_starts_only_one_reviewer(self):
        self.job('a','ready');self.job('b','ready')
        with patch.object(self.w,'poll'),patch.object(self.w,'launch') as launch:self.w.tick(claim=False)
        self.assertEqual(launch.call_count,1);self.assertEqual(launch.call_args.args[1],'reviewing')
    def test_pressure_isolates_parser_not_review(self):
        a=self.job('a','reviewing');b=self.job('b','parsing');self.w.guard.check.return_value='[memory_pressure] low'
        with patch.object(self.w,'poll'),patch.object(self.w,'fail') as fail:self.w.tick()
        self.assertEqual(fail.call_args.args[0],b);self.assertIn('a',self.w.jobs)
    def test_restart_resumes_ready_but_not_interrupted_api(self):
        self.job('a','ready');self.job('b','reviewing');self.w.save();self.w.jobs={};self.w.restore()
        self.assertEqual(set(self.w.jobs),{'a'})
        calls=self.client.post.call_args_list
        self.assertEqual(sum(x.args[0]=='fail' for x in calls),1)
    def test_lost_lease_stops_only_that_paper(self):
        a=self.job('a','ready');b=self.job('b','ready');a['lease_lost']=True
        with patch.object(self.w,'fail') as fail:self.w.poll()
        self.assertEqual(fail.call_args.args[0],a)
    def test_drain_disallows_claim_but_starts_ready_review(self):
        self.job('a','ready');self.w.drain.touch()
        with patch.object(self.w,'poll'),patch.object(self.w,'launch') as launch:self.w.tick()
        launch.assert_called_once();self.client.post.assert_not_called()
    def test_heartbeat_renews_both_lanes(self):
        self.job('a','reviewing');self.job('b','parsing')
        def stop_wait(seconds):self.w.stop.set()
        with patch.object(self.w.stop,'wait',side_effect=stop_wait),patch.object(self.w,'report'):
            self.w.heartbeat()
        ids=[x.args[1]['task_id'] for x in self.client.post.call_args_list if x.args[0]=='heartbeat']
        self.assertEqual(ids,['a','b'])

    def test_resource_monitor_failure_still_runs_service_recovery(self):
        self.w.guard.check.return_value='[resource_oom] missing monitor'
        with patch.object(self.w,'poll'),patch.object(self.w.recovery,'check') as recover:
            self.w.tick()
        recover.assert_called_once()

    def test_missing_tei_does_not_load_docling(self):
        from paper_citation_pipeline.ledger.parse_stage import DoclingAfterGrobid
        worker=Mock();gate=DoclingAfterGrobid(worker,Path(self.tmp.name)/'missing.xml')
        with self.assertRaises(RuntimeError):gate.run('pdf','output','log',1800)
        worker.run.assert_not_called()
    def test_valid_tei_allows_docling(self):
        from paper_citation_pipeline.ledger.parse_stage import DoclingAfterGrobid
        tei=Path(self.tmp.name)/'ok.xml';tei.write_text('<TEI/>');worker=Mock()
        DoclingAfterGrobid(worker,tei).run('pdf','output','log',1800)
        worker.run.assert_called_once_with('pdf','output','log',1800)

    def test_parser_preparation_does_not_contend_with_numbering_writer(self):
        from paper_citation_pipeline.ledger.worker import prepare,digest
        from paper_citation_pipeline.numbering import initialize,locked
        root=Path(self.tmp.name);pdf=root/'paper.pdf';pdf.write_bytes(b'%PDF-test')
        state=root/'numbering.json';initialize(state,12,34)
        task={'id':'paper-task','attempts':1,'input_location':str(pdf),'input_sha256':digest(pdf)}
        profile={'roots':[str(root)],'config':{'id_state':str(state)}}
        before=state.read_bytes()
        with locked(state):
            work,config=prepare(task,profile,root/'runs',numbering_read_only=True)
        self.assertTrue(config.exists());self.assertEqual(state.read_bytes(),before)
    def test_readonly_numbering_still_rejects_invalid_state(self):
        from paper_citation_pipeline.ledger.worker import prepare,digest
        root=Path(self.tmp.name);pdf=root/'paper.pdf';pdf.write_bytes(b'%PDF-test')
        state=root/'numbering.json';state.write_text('{}')
        task={'id':'paper-task','attempts':1,'input_location':str(pdf),'input_sha256':digest(pdf)}
        with self.assertRaises(ValueError):
            prepare(task,{'roots':[str(root)],'config':{'id_state':str(state)}},root/'runs',numbering_read_only=True)
