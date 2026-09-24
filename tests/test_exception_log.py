import json,tempfile,unittest,sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from paper_citation_pipeline.exception_log import collect_exceptions,save_exceptions
from paper_citation_pipeline.cli import main

class ExceptionLogTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.out=self.root/'out';self.out.mkdir();self.inputs=self.root/'input';self.inputs.mkdir()
    def tearDown(self):self.temp.cleanup()
    def test_zero_hits_failures_and_missing_inputs(self):
        for name in ['zero','bad','notread','good']:(self.inputs/(name+'.pdf')).write_bytes(b'PDF')
        (self.out/'json').mkdir()
        for name,n in [('zero',0),('good',1)]:
            (self.out/'json'/(name+'.json')).write_text(json.dumps({'target_candidates':[{}]*n}))
        (self.out/'manifest.json').write_text(json.dumps([{'paper':'zero','readiness':'ready_with_issues','target_candidates':0,'pdf_target_mentions':2},{'paper':'bad','readiness':'failed','validation_errors':['PDF无法打开']},{'paper':'good','readiness':'ready_for_annotation','target_candidates':1}]))
        path=collect_exceptions(self.out,'UNEP',self.inputs);data=json.loads(path.read_text())
        self.assertEqual(data['count'],3)
        self.assertEqual({i['paper'] for i in data['issues']},{'zero','bad','notread'})
        text=path.with_suffix('.txt').read_text();self.assertIn('zero.pdf',text);self.assertIn('UNEP',text);self.assertIn('不代表原文确定不存在',text)
    def test_zero_candidates_distinguishes_reference_found_but_link_missing(self):
        (self.out/'json').mkdir()
        (self.out/'json/p.json').write_text(json.dumps({'target_candidates':[],'citation_index':{'references':[{'organization_candidate':{'organization_id':'UNEP'}}]}}))
        (self.out/'manifest.json').write_text(json.dumps([{'paper':'p','readiness':'ready_with_issues','target_candidates':0}]))
        report=json.loads(collect_exceptions(self.out,'UNEP').read_text())
        self.assertIn('已识别目标参考文献1条',report['issues'][0]['reason'])
        self.assertIn('未建立正文',report['issues'][0]['reason'])
    def test_missing_json_is_named(self):
        (self.out/'manifest.json').write_text(json.dumps([{'paper':'paper','readiness':'ready_for_annotation','target_candidates':1}]))
        path=collect_exceptions(self.out,'WHO')
        self.assertEqual(json.loads(path.read_text())['issues'][0]['kind'],'解析JSON未读到')
    def test_local_and_ai_same_issue_counted_once(self):
        quality={'checks':[{'id':'q1','kind':'required_blank_in_source','status':'warning','field':'title'}],
                 'ai_checks':[{'id':'q1','status':'warning','reason':'same issue'}]}
        (self.out/'citations.quality.json').write_text(json.dumps(quality))
        path=collect_exceptions(self.out,'UNEP')
        self.assertEqual(json.loads(path.read_text())['count'],1)
    def test_keys_redacted_in_both_formats(self):
        path=save_exceptions(self.out/'exceptions.json',[{'kind':'测试','reason':'secret-value'}],'UNEP',secrets=('secret-value',))
        for p in [path,path.with_suffix('.txt')]:self.assertNotIn('secret-value',p.read_text())
    def test_cli_preflight_failure_persists_log(self):
        code=main(['run','--input',str(self.inputs),'--output',str(self.out),'--target','UNEP','--id-state',str(self.root/'missing-numbering.json')])
        self.assertEqual(code,2)
        data=json.loads((self.out/'exceptions.json').read_text())
        self.assertTrue(any(i['kind']=='文件或运行异常' for i in data['issues']))
        self.assertIn('missing-numbering.json',(self.out/'exceptions.txt').read_text())

if __name__=='__main__':unittest.main()
