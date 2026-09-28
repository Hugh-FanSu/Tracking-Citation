"""Durable per-paper Excel snapshots; JSON remains the source of truth."""
import time
import json
from pathlib import Path
from .excel import export_packets, digest
from .progress import Progress
from .numbering import atomic_json


class QuietProgress:
    def advance(self, *args, **kwargs):pass
    def finish(self):pass
    def emit(self, *args, **kwargs):pass


class StreamingExport:
    def __init__(self, config, total):
        self.config = config
        self.paths = []
        self.output = Path(config['output'])
        self.progress = Progress('逐篇保存模板', total, self.output.with_suffix('.progress.json'))
        self.saved = False
        self.events = []

    def advance(self, path, failed=False, *, skipped=False):
        start = time.perf_counter()
        if not failed and not skipped:self.paths.append(Path(path))
        try:
            if not failed and not skipped:
                c = self.config
                export_packets(self.paths,c['template'],c['mapping'],self.output,
                               self.saved or c.get('overwrite',False),id_state=c['id_state'],
                               progress=QuietProgress())
                self.saved = True
                from .quality import inspect_workbook
                _,checks=inspect_workbook(self.output)
                errors=[c for c in checks if c.get('status')=='error']
                if errors:raise ValueError(f'Saved Excel failed structural readback: {errors}')
            self.progress.advance(Path(path).stem,failed,skipped=skipped)
            self.events.append(dict(paper=Path(path).stem,status='excluded' if skipped else 'parse_failed' if failed else 'saved',
                                    saved_papers=len(self.paths) if self.saved else 0,
                                    seconds=round(time.perf_counter()-start,3)))
        except Exception as exc:
            self.events.append(dict(paper=Path(path).stem,status='save_failed',error=str(exc)))
            self.progress.advance(Path(path).stem,True)
            raise
        finally:
            atomic_json(self.output.with_suffix('.checkpoints.json'),{'events':self.events,'complete':False})

    def finish(self):
        self.progress.finish()
        checkpoint={'events':self.events,'complete':True}
        if self.saved and not any(e['status']=='save_failed' for e in self.events):
            checkpoint['snapshot']=snapshot_fingerprints(self.paths,self.config['template'],
                self.config['mapping'],self.output,self.config['id_state'])
        atomic_json(self.output.with_suffix('.checkpoints.json'),checkpoint)


def snapshot_fingerprints(paths, template, mapping, output, id_state):
    """Fingerprint every input and saved artifact, including the numbering ledger."""
    output=Path(output)
    files=[Path(template),Path(mapping),Path(id_state),output,
           output.with_suffix('.provenance.json'),output.with_suffix('.fill-manifest.json')]
    return {'sources':{str(Path(p).resolve()):digest(p) for p in paths},
            'artifacts':{str(p.resolve()):digest(p) for p in files}}


def reuse_completed_snapshot(paths, template, mapping, output, id_state):
    """Fail closed on interrupted, changed or legacy snapshots. Final QA still runs."""
    output=Path(output)
    try:
        checkpoint=json.loads(output.with_suffix('.checkpoints.json').read_text(encoding='utf-8'))
        if checkpoint.get('complete') is not True or not checkpoint.get('snapshot'):return None
        if any(e.get('status')=='save_failed' for e in checkpoint.get('events',[])):return None
        current=snapshot_fingerprints(paths,template,mapping,output,id_state)
        if current!=checkpoint['snapshot']:return None
        summary=json.loads(output.with_suffix('.provenance.json').read_text(encoding='utf-8'))
        return dict(summary,reused_completed_stream_snapshot=True)
    except (OSError,ValueError,TypeError,KeyError):
        return None
