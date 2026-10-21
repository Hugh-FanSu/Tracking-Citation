import json
import tempfile
import threading
import time
import unittest
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from paper_citation_pipeline.ledger.store import Store
from paper_citation_pipeline.ledger.server import make_server


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name)/'ledger.db')
        self.store.import_csv('title,doi\nExample,10.1234/abc\n','UNEP','catalog','batch1')
        self.pid=self.store.view()['papers'][0]['id']

    def tearDown(self):self.tmp.cleanup()

    def task(self):
        self.store.update_download(self.pid,{'download':'available','location':'/worker/paper.pdf','sha256':'a'*64})
        return self.store.enqueue(self.pid,'UNEP','v1','config1')

    def test_import_dedup_and_rollback(self):
        d=self.store.import_csv('title,doi\nSame,https://doi.org/10.1234/ABC\n','WHO','catalog','batch2')
        self.assertEqual(d['new_papers'],0)
        self.assertEqual(set(self.store.view()['papers'][0]['organizations']),{'WHO','UNEP'})
        with self.assertRaises(ValueError):
            self.store.import_csv('title,doi\nNew,10.1234/new\nBad,wrong\n','UNEP','catalog','batch3')
        self.assertEqual(self.store.view()['total'],1)

    def test_permission_not_eligible(self):
        self.store.update_download(self.pid,{'download':'permission_required','note':'await access'})
        with self.assertRaises(ValueError):self.store.enqueue(self.pid,'UNEP','v1','c')
        self.assertEqual(self.store.view()['summary']['permission_required'],1)

    def test_concurrent_claim_exactly_one(self):
        task=self.task()
        self.assertEqual(self.store.enqueue(self.pid,'UNEP','v1','config1')['id'],task['id'])
        with ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(lambda i:self.store.claim('worker'+str(i)),range(8)))
        self.assertEqual(sum(r is not None for r in results),1)

    def test_expired_worker_cannot_complete(self):
        self.task();old=self.store.claim('old')
        with self.store.db() as c:c.execute('UPDATE tasks SET lease_until=0')
        new=self.store.claim('new')
        with self.assertRaises(ValueError):self.store.task_action(old['id'],'complete',dict(worker='old',lease_token=old['lease_token'],result={'json_location':'x','json_sha256':'b'*64}))
        self.store.task_action(new['id'],'complete',dict(worker='new',lease_token=new['lease_token'],result={'json_location':'x','json_sha256':'b'*64}))
        self.assertEqual(self.store.view()['task_counts'],{'completed':1})

    def test_input_change_blocks_stale_queue(self):
        self.task()
        self.store.update_download(self.pid,{'download':'available','location':'new','sha256':'b'*64})
        self.assertIsNone(self.store.claim('w'))

    def test_attempt_cap(self):
        self.task()
        for i in range(3):
            self.assertIsNotNone(self.store.claim('w'))
            with self.store.db() as c:c.execute('UPDATE tasks SET lease_until=0')
        self.assertIsNone(self.store.claim('w'))
        self.assertEqual(self.store.view()['task_counts'],{'failed':1})

    def test_http_auth_and_import(self):
        server=make_server(Path(self.tmp.name)/'http.db',port=0,token='test-token')
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        url='http://127.0.0.1:'+str(server.server_address[1])
        open_url=urllib.request.build_opener(urllib.request.ProxyHandler({})).open
        try:
            with open_url(url) as r:self.assertIn('论文中央台账',r.read().decode())
            with self.assertRaises(urllib.error.HTTPError) as e:open_url(url+'/api/state')
            self.assertEqual(e.exception.code,401)
            data=json.dumps({'csv':'title,doi\nA,10.1234/a\n','organization':'UNEP','source':'s','batch':'b'}).encode()
            req=urllib.request.Request(url+'/api/import',data=data,headers={'Authorization':'Bearer test-token','Content-Type':'application/json'})
            with open_url(req) as r:self.assertEqual(json.load(r)['new_papers'],1)
        finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()

class RemoteWorkerTests(unittest.TestCase):
    def test_profile_filter_and_offline(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d)/'s.db')
            store.import_csv('title,doi\nA,10.1234/a\n','UNEP','s','b')
            pid=store.view()['papers'][0]['id']
            store.update_download(pid,dict(download='available',location='/remote/a.pdf',sha256='a'*64))
            store.enqueue(pid,'UNEP','v1','c1')
            self.assertIsNone(store.claim('wrong',[dict(organization='WHO',version='v1',config_version='c1')]))
            self.assertIsNotNone(store.claim('right',[dict(organization='UNEP',version='v1',config_version='c1')]))
            store.worker_report('remote',{'phase':'idle'})
            self.assertTrue(store.workers()[0]['online'])
            with store.db() as c:c.execute('UPDATE workers SET last_seen=0')
            self.assertFalse(store.workers()[0]['online'])

    def test_prepare_uses_cli_config_and_rejects_changed_pdf(self):
        from paper_citation_pipeline.ledger.worker import prepare, digest
        from paper_citation_pipeline.numbering import initialize
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);pdf=root/'a.pdf';pdf.write_bytes(b'%PDF-test')
            state=root/'ids.json';initialize(state,0,0)
            p=dict(roots=[d],config=dict(target='UNEP',id_state=str(state)))
            task=dict(id='t1',attempts=1,input_location=str(pdf),input_sha256=digest(pdf))
            work,cfg=prepare(task,p,root/'runs')
            config=json.loads(cfg.read_text())
            self.assertEqual(config['id_state'],str(state))
            self.assertEqual((Path(config['input'])/'a.pdf').read_bytes(),pdf.read_bytes())
            pdf.write_bytes(b'changed')
            with self.assertRaises(ValueError):prepare(dict(task,id='t2'),p,root/'runs')
