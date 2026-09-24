import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from paper_citation_pipeline.stage_monitor import StageMonitor

class StageMonitorTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name);self.cfg=self.root/'api.json';self.cfg.write_text('{}')
 def tearDown(self):self.t.cleanup()
 def test_three_stages_bounded_and_resume_cached(self):
  with patch('paper_citation_pipeline.stage_monitor.Client') as client:
   def reply(messages,**kw):
    self.assertEqual(kw,{'attempts':1,'max_tokens':1536});p=json.loads(messages[-1]['content'])
    return {'stage':p['stage'],'status':'ok','findings':[]},{'usage':{'total_tokens':12}}
   client.return_value.request.side_effect=reply
   for _ in range(2):
    m=StageMonitor(self.cfg,self.root)
    for stage in ('parsing','filling','exceptions'):m.run(stage,[{'paper':'p1','target_candidates':2}])
    self.assertFalse(m.failed)
   self.assertEqual(client.return_value.request.call_count,3)
 def test_failures_are_logged_and_not_retried(self):
  with patch('paper_citation_pipeline.stage_monitor.Client') as client:
   client.return_value.key='SECRET';client.return_value.request.side_effect=ValueError('failure SECRET')
   m=StageMonitor(self.cfg,self.root);m.run('parsing',[{'paper':'p1'}]);m.run('parsing',[{'paper':'p1'}]);self.assertTrue(m.failed)
   self.assertEqual(client.return_value.request.call_count,1)
   self.assertNotIn('SECRET',(self.root/'api-stages.json').read_text())
 def test_unknown_paper_rejected(self):
  with self.assertRaises(ValueError):StageMonitor.validate({'stage':'parsing','status':'warning','findings':[{'paper':'invented','code':'a','message':'b'}]},'parsing',{'p1'})
 def test_model_count_comparison_without_evidence_is_not_an_error(self):
  from paper_citation_pipeline.stage_monitor import ground_result
  result={'stage':'parsing','status':'error','findings':[{'paper':'p1','code':'count_mismatch','message':'5 citations vs 2 references'}]}
  effective,rejected=ground_result(result,[{'paper':'p1','target_candidates':5,'target_references':2}],{})
  self.assertEqual(effective['status'],'ok');self.assertEqual(len(rejected),1);self.assertEqual(result['status'],'error')
 def test_saved_cell_error_is_supported(self):
  from paper_citation_pipeline.stage_monitor import ground_result
  result={'stage':'filling','status':'error','findings':[{'paper':'__batch__','code':'cell_mismatch','message':'wrong cell'}]}
  effective,rejected=ground_result(result,[],{'saved_workbook':{'issues':[{'kind':'cell_mismatch','status':'error'}]}})
  self.assertEqual(effective['status'],'error');self.assertEqual(rejected,[])
 def test_oversize_input_never_calls_api(self):
  with patch('paper_citation_pipeline.stage_monitor.Client') as client:
   m=StageMonitor(self.cfg,self.root);m.run('parsing',[{'paper':'p1'}],{'huge':'x'*25000});client.assert_not_called();self.assertTrue(m.failed)

if __name__=='__main__':unittest.main()
