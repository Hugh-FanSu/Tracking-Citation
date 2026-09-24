"""Plain stderr progress bars also readable in agent logs (no terminal dependency)."""
import sys
import time
from pathlib import Path
from .numbering import atomic_json


class Progress:
    def __init__(self, label, total, path=None):
        self.label, self.total, self.path = label, total, Path(path) if path else None
        self.completed = self.failed = 0
        self.start = time.monotonic()
        self.emit('running')

    def emit(self, status, paper=None):
        self.status = status
        fraction = self.completed / self.total if self.total else 0
        bar = '#' * int(24 * fraction) + '-' * (24 - int(24 * fraction))
        data = dict(stage=self.label, processed=self.completed, total=self.total,
                    succeeded=self.completed-self.failed, failed=self.failed, status=status,
                    current_paper=paper, elapsed_seconds=round(time.monotonic()-self.start, 2))
        print(f'{self.label} [{bar}] {self.completed}/{self.total} 篇 | 失败 {self.failed} | {status}' + (f' | {paper}' if paper else ''), file=sys.stderr, flush=True)
        if self.path: atomic_json(self.path, data)

    def advance(self, paper, failed=False):
        self.completed += 1
        self.failed += int(failed)
        self.emit('running', paper)

    def finish(self):
        self.emit('completed_with_failures' if self.failed else 'completed')
