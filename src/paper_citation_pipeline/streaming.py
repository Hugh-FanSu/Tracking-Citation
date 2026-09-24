"""Durable per-paper Excel snapshots; JSON remains the source of truth."""
import time
from pathlib import Path
from .excel import export_packets
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

    def advance(self, path, failed=False):
        start = time.perf_counter()
        if not failed:self.paths.append(Path(path))
        try:
            if not failed:
                c = self.config
                export_packets(self.paths,c['template'],c['mapping'],self.output,
                               self.saved or c.get('overwrite',False),id_state=c['id_state'],
                               progress=QuietProgress())
                self.saved = True
                from .quality import inspect_workbook
                _,checks=inspect_workbook(self.output)
                errors=[c for c in checks if c.get('status')=='error']
                if errors:raise ValueError(f'Saved Excel failed structural readback: {errors}')
            self.progress.advance(Path(path).stem,failed)
            self.events.append(dict(paper=Path(path).stem,status='parse_failed' if failed else 'saved',
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
        atomic_json(self.output.with_suffix('.checkpoints.json'),{'events':self.events,'complete':True})
