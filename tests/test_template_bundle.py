import json,sys,tempfile,unittest
from pathlib import Path
from openpyxl import Workbook
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from paper_citation_pipeline.template_bundle import load_bundle

class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        wb=Workbook();wb.active.title='citations';wb.active.append(['paper_id','raw_marker']);wb.save(self.root/'引用采集模板.xlsx')
        (self.root/'名称变体.json').write_text(json.dumps({'id':'WHO','canonical_name':'World Health Organization','aliases':['WHO']}))
    def tearDown(self):self.temp.cleanup()
    def test_exact_files_and_read_only_auto_mapping(self):
        before={p.name:p.read_bytes() for p in self.root.iterdir()};b=load_bundle(self.root)
        self.assertEqual(b['target'],'WHO');self.assertEqual(b['mapping_spec']['sheets'][0]['columns']['paper_id'],'paper_id')
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.root.iterdir()})
    def test_missing_alias_list_does_not_guess_target(self):
        (self.root/'名称变体.json').unlink()
        with self.assertRaises(ValueError):load_bundle(self.root)
    def test_explicit_invalid_mapping_is_not_ignored(self):
        (self.root/'字段映射.json').write_text('{"sheets":[]}')
        with self.assertRaises(ValueError):load_bundle(self.root)

    def test_selected_organization_cannot_use_other_aliases(self):
        with self.assertRaises(ValueError):load_bundle(self.root,expected_org='UNEP')
        self.assertEqual(load_bundle(self.root,expected_org='WHO')['target'],'WHO')
    def test_variant_selection_and_path_escape(self):
        (self.root/'名称变体-组一.json').write_text(json.dumps({'id':'WHO','aliases':['W.H.O.'],'canonical_name':'WHO'}))
        self.assertEqual(load_bundle(self.root,expected_org='WHO',alias_filename='名称变体-组一.json')['aliases'].name,'名称变体-组一.json')
        with self.assertRaises(ValueError):load_bundle(self.root,alias_filename='../名称变体.json')
    def test_missing_org_never_falls_back(self):
        from paper_citation_pipeline.organizations import organization_dir
        with self.assertRaises(ValueError):load_bundle(organization_dir(self.root,'UNEP'),expected_org='UNEP')

if __name__=='__main__':unittest.main()
