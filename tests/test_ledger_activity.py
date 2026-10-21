import json,os,sqlite3,tempfile,unittest
from pathlib import Path
from paper_citation_pipeline.ledger.activity import build_activity

class ActivityTests(unittest.TestCase):
 def test_window_filter_dedup_and_real_usage_including_failed_review(self):
  with tempfile.TemporaryDirectory() as temp:
   c=sqlite3.connect(':memory:');c.executescript('CREATE TABLE tasks(id,paper_id,organization,attempts,status,updated);CREATE TABLE events(task_id,action,created);')
   c.executemany('INSERT INTO tasks VALUES(?,?,?,?,?,?)',[('a','p','UNEP',1,'completed',9950),('b','p','UNEP',1,'completed',9960),('c','q','WHO',1,'completed',9970)])
   c.executemany('INSERT INTO events VALUES(?,?,?)',[('a','complete',9950),('b','complete',9960),('a','complete',5000),('c','complete',9970)])
   folder=Path(temp)/'a/attempt-1/output/semantic-review';folder.mkdir(parents=True)
   records=[dict(status='completed',response_id='same',served_model='glm-4.7',usage={'prompt_tokens':10,'completion_tokens':4}),dict(status='failed',response_id='other',served_model='glm-5.3-flash',usage={'prompt_tokens':8,'completion_tokens':2}),dict(status='completed',response_id='same',usage={'prompt_tokens':10,'completion_tokens':4}),dict(status='failed',error='timeout'),dict(status='started')]
   for i,d in enumerate(records):
    p=folder/f'{i}.json';p.write_text(json.dumps(d));os.utime(p,(9990,9990))
   a=build_activity(c,temp,'UNEP',now=10000)
   self.assertEqual(a['papers'],1);self.assertEqual(len(a['points']),60)
   self.assertEqual(a['input_tokens'],18);self.assertEqual(a['output_tokens'],6)
   self.assertEqual(a['usage_missing'],1);self.assertEqual(a['in_flight'],1)
   self.assertEqual(a['requests'],2);self.assertEqual(len(a['models']),2)
   self.assertEqual(build_activity(c,temp,'WHO',now=10000)['papers'],1)
 def test_empty_window_is_zero_not_fake_activity(self):
  c=sqlite3.connect(':memory:');c.executescript('CREATE TABLE tasks(id,paper_id,organization,attempts,status,updated);CREATE TABLE events(task_id,action,created);')
  with tempfile.TemporaryDirectory() as temp:
   a=build_activity(c,temp,now=10000)
   self.assertEqual(a['papers'],0);self.assertEqual(a['requests'],0)
   self.assertTrue(all(p['input_tokens']==0 for p in a['points']))
