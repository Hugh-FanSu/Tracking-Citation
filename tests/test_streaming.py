import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from openpyxl import load_workbook
import test_tool
from paper_citation_pipeline.streaming import StreamingExport
from paper_citation_pipeline.engine.runtime.docling_worker import Worker


def fake_worker(conn, ocr):
    while True:
        request=conn.recv()
        if request is None:break
        pdf, output, log = request
        if pdf == 'timeout':time.sleep(10)
        if pdf == 'crash':os._exit(1)
        Path(output).write_text(json.dumps(dict(status='success',page_count=os.getpid(),errors=[])))
        conn.send({'ok':True})


class StreamingTests(unittest.TestCase):
    setUp=test_tool.ToolTests.setUp
    tearDown=test_tool.ToolTests.tearDown
    write=test_tool.ToolTests.write
    packet=test_tool.ToolTests.packet
    template=test_tool.ToolTests.template

    def test_first_paper_durable_before_second_and_save_failure_preserves_it(self):
        template,mapping=self.template();original=template.read_bytes();out=self.root/'filled.xlsx'
        c=dict(template=str(template),mapping=str(mapping),output=str(out),id_state=str(self.state))
        stream=StreamingExport(c,3)
        one=self.write('one.json',self.packet());stream.advance(one)
        self.assertEqual(load_workbook(out).active.max_row,2)
        progress=json.loads(out.with_suffix('.progress.json').read_text())
        self.assertEqual((progress['processed'],progress['total']),(1,3))
        before=out.read_bytes()
        d=self.packet();d['paper_id']='P2';d['source']['sha256']='second';d['source']['pdf']='second.pdf'
        two=self.write('two.json',d)
        with patch('openpyxl.workbook.workbook.Workbook.save',side_effect=OSError('locked')):
            with self.assertRaises(OSError):stream.advance(two)
        self.assertEqual(out.read_bytes(),before)
        d=self.packet();d['paper_id']='P3';d['source']['sha256']='third';d['source']['pdf']='third.pdf'
        stream.advance(self.write('three.json',d));stream.finish()
        self.assertEqual(load_workbook(out).active.max_row,4)
        self.assertEqual(template.read_bytes(),original)

    def test_failed_parser_not_exported(self):
        template,mapping=self.template();out=self.root/'filled.xlsx'
        stream=StreamingExport(dict(template=str(template),mapping=str(mapping),output=str(out),id_state=str(self.state)),2)
        stream.advance(self.root/'missing.json',True)
        self.assertFalse(out.exists())
        stream.advance(self.write('good.json',self.packet()))
        self.assertEqual(load_workbook(out).active.max_row,2)


class WorkerTests(unittest.TestCase):
    def test_reuses_process_then_recovers_after_timeout_and_crash(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/'doc.json';log=Path(folder)/'log'
            worker=Worker(target=fake_worker)
            try:
                a=worker.run('one',out,log,5)
                b=worker.run('two',out,log,5)
                self.assertEqual(a['page_count'],b['page_count'])
                with self.assertRaises(TimeoutError):worker.run('timeout',out,log,0.05)
                c=worker.run('three',out,log,5)
                self.assertNotEqual(a['page_count'],c['page_count'])
                with self.assertRaises((EOFError,ConnectionError)):worker.run('crash',out,log,5)
                self.assertEqual(worker.run('four',out,log,5)['status'],'success')
            finally:worker.close()
