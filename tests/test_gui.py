import json
from pathlib import Path
import tempfile
import unittest
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from paper_citation_pipeline.gui import build_command,progress_files


class GuiTests(unittest.TestCase):
    def test_new_task_requires_explicit_numbers(self):
        with self.assertRaises(ValueError):build_command(dict(input='pdfs',template='blank.xlsx',target='WHO'),Path('project'))
        cmd=build_command({'input':'PDFs with spaces','template':'blank.xlsx','target':'WHO','paper-current':'25','record-current':'100'},Path('project'))
        self.assertIn('--non-interactive',cmd);self.assertIn('PDFs with spaces',cmd)
        self.assertEqual(cmd[cmd.index('--paper-current')+1],'25')
    def test_existing_ledger_ignores_unrelated_counter_fields(self):
        cmd=build_command({'input':'pdfs','template':'t.xlsx','target':'WHO','id-state':'state.json','paper-current':'0'},Path('p'))
        self.assertNotIn('--paper-current',cmd);self.assertIn('state.json',cmd)
    def test_resume_does_not_silently_overwrite(self):
        cmd=build_command({'config':'run.json'},Path('p'));self.assertNotIn('--overwrite-excel',cmd)
        self.assertIn('--overwrite-excel',build_command({'config':'run.json','overwrite':True},Path('p')))
    def test_progress_paths_respect_config(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t).resolve();(root/'run.json').write_text(json.dumps({'output':'out','excel':'custom/filled.xlsx'}))
            paths=progress_files(root)
            self.assertEqual(paths,[root/'out/conversion-progress.json',root/'custom/filled.progress.json',root/'custom/filled.quality-progress.json'])

if __name__=='__main__':unittest.main()
