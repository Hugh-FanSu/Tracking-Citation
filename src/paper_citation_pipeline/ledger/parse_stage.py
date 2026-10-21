"""One PDF, engines only. Exit (including Docling child) before handing off."""
import json
import logging
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from ..language import inspect_pdf


class DoclingAfterGrobid:
    """Fresh serial parse: do not load Docling after a failed GROBID response."""
    def __init__(self,worker,tei):self.worker,self.tei=worker,tei
    def run(self,*args):
        from lxml import etree
        if not self.tei.is_file():raise RuntimeError('GROBID未生成TEI，跳过Docling以释放解析通道')
        etree.parse(str(self.tei))
        return self.worker.run(*args)


def parse(config_path):
    cfg=json.loads(Path(config_path).read_text())
    pdfs=[p for p in Path(cfg['input']).iterdir() if p.is_file() and p.suffix.lower()=='.pdf']
    if len(pdfs)!=1:raise ValueError('Parse stage requires exactly one PDF')
    pdf=pdfs[0];out=Path(cfg['output']);cache=out/'_parser'
    for folder in ['tei','json','md','docling']:(cache/folder).mkdir(parents=True,exist_ok=True)
    (out/'logs').mkdir(exist_ok=True)
    language=inspect_pdf(pdf)
    if language['status']!='english':
        # Existing CLI rechecks language and emits its usual excluded packet.
        (cache/'json'/(pdf.stem+'.json')).write_text(json.dumps({'source':{'pdf':str(pdf)}}))
        return
    runtime=Path(__file__).resolve().parents[1]/'engine/runtime'
    sys.path.insert(0,str(runtime))
    from pipeline import process_pdf
    from docling_worker import Worker
    os.environ['PAPER_STAGE_WORKERS']='1'
    worker=Worker(cfg.get('ocr',False))
    args=SimpleNamespace(output=cache,logs=out/'logs',grobid_url=cfg.get('grobid_url','http://localhost:8070'),grobid_timeout=600,docling_timeout=1800,retries=int(os.environ.get('PAPER_GROBID_RETRIES','0')),ocr=cfg.get('ocr',False),resume=False,docling_worker=DoclingAfterGrobid(worker,cache/'tei'/(pdf.stem+'.tei.xml')))
    try:
        report=process_pdf(pdf,args)
        (out/'engine-summary.json').write_text(json.dumps([report]))
        if report['status']!='success':raise RuntimeError('PDF engines failed; see stage logs')
    finally:worker.close()


if __name__=='__main__':
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    parse(sys.argv[1])
