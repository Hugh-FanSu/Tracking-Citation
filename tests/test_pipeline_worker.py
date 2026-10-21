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

    def test_timeout_stops_parser_and_keeps_review_running(self):
        import time
        a=self.job('a','parsing');b=self.job('b','reviewing')
        for j,elapsed in ((a,601),(b,601)):
            j.update(proc=Mock(),log=Mock(),monotonic=time.monotonic()-elapsed)
            j['proc'].poll.return_value=None
        with patch('paper_citation_pipeline.ledger.pipeline_worker.stop_process') as stop,patch.object(self.w,'save'):
            self.w.poll()
        stop.assert_called_once_with(a['proc'])
        self.assertEqual(set(self.w.jobs),{'b'})
        reason=self.client.post.call_args.args[1]['error']
        self.assertIn('[stage_timeout]',reason)
        self.assertIn('600秒',reason)
        self.assertEqual(self.client.post.call_args.args[0],'fail')

    def test_review_timeout_does_not_replay_model_or_stop_parser(self):
        import time
        a=self.job('a','reviewing');b=self.job('b','parsing')
        for j,elapsed in ((a,901),(b,30)):
            j.update(proc=Mock(),log=Mock(),monotonic=time.monotonic()-elapsed)
            j['proc'].poll.return_value=None
        with patch('paper_citation_pipeline.ledger.pipeline_worker.stop_process'),patch.object(self.w,'save'),patch.object(self.w,'launch') as launch:
            self.w.poll()
        self.assertEqual(set(self.w.jobs),{'b'});launch.assert_not_called()
        self.assertIn('900秒',self.client.post.call_args.args[1]['error'])

    def test_finished_stage_at_deadline_is_kept(self):
        import time
        a=self.job('a','parsing')
        a.update(proc=Mock(),log=Mock(),monotonic=time.monotonic()-601,started_at=time.time()-601)
        a['proc'].poll.return_value=0
        self.w.poll()
        self.assertEqual(a['stage'],'ready');self.client.post.assert_not_called()

    def test_report_exposes_stage_time_and_limit(self):
        import time
        a=self.job('a','parsing');a['started_at']=time.time()-70
        self.w.report()
        row=self.client.post.call_args.args[1]['payload']['pipeline_jobs'][0]
        self.assertGreaterEqual(row['elapsed_seconds'],70)
        self.assertEqual(row['timeout_seconds'],600)

    def test_timeouts_do_not_lock_queue(self):
        from paper_citation_pipeline.ledger.resource_guard import ResourceGuard
        guard=ResourceGuard(self.tmp.name)
        for _ in range(5):guard.failure('[stage_timeout] slow paper')
        self.assertFalse(guard.path.exists());self.assertEqual(guard.failures,0)

    def test_watchdog_terminates_real_child_and_frees_lane(self):
        import os,subprocess,sys,time
        a=self.job('slow','parsing');work=Path(a['work']);work.mkdir()
        proc=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],start_new_session=(os.name=='posix'))
        from paper_citation_pipeline.ledger.worker import stop_process
        self.addCleanup(stop_process,proc)
        a.update(proc=proc,log=(work/'process.log').open('a'),monotonic=time.monotonic()-601)
        self.w.poll()
        self.assertIsNotNone(proc.poll())
        self.assertFalse(self.w.jobs)
        self.assertEqual(json.loads(self.w.state.read_text()),[])
        self.assertIn('[stage_timeout]',self.client.post.call_args.args[1]['error'])
