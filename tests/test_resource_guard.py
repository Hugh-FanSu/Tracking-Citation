import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from paper_citation_pipeline.ledger.resource_guard import ResourceGuard

class GuardTests(unittest.TestCase):
    def test_oom_enters_recovery_without_permanent_lock(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'events';p.write_text('oom 0\noom_kill 0\n')
            with patch.dict(os.environ, {'PAPER_OOM_EVENT_FILES': str(p)}):
                g=ResourceGuard(d);g.events=g.read_events();p.write_text('oom 1\noom_kill 1\n')
                self.assertTrue(g.check(True))
                self.assertFalse(g.path.exists())
                self.assertTrue(g.pressure_path.exists())
    def test_low_memory_and_recovery(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'PAPER_OOM_EVENT_FILES':''}):
            g=ResourceGuard(d)
            with patch('psutil.virtual_memory',return_value=SimpleNamespace(available=1200*1024**2)):
                self.assertTrue(g.check());self.assertFalse(g.check(True))
            with patch('psutil.virtual_memory',return_value=SimpleNamespace(available=3000*1024**2)):
                self.assertFalse(g.check())
            with patch('psutil.virtual_memory',return_value=SimpleNamespace(available=500*1024**2)):
                self.assertTrue(g.check(True));self.assertFalse(g.path.exists())
    def test_failure_breaker(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'PAPER_OOM_EVENT_FILES':''}):
            g=ResourceGuard(d)
            g.failure('x');g.failure('x');self.assertFalse(g.path.exists())
            g.success();g.failure('x');self.assertFalse(g.path.exists())
            g.failure('x');g.failure('x');self.assertTrue(g.path.exists())

    def test_quarantine_recovers_and_does_not_retry(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'PAPER_OOM_EVENT_FILES':''}):
            g=ResourceGuard(d)
            with patch('time.time',return_value=100):
                g.quarantine({'id':'one','paper_id':'paper'}, '[memory_pressure] low')
            with patch('psutil.virtual_memory',return_value=SimpleNamespace(available=3000*1024**2)):
                with patch('time.time',return_value=110):self.assertTrue(g.check())
                with patch('time.time',return_value=161):self.assertFalse(g.check())
            self.assertFalse(g.path.exists())
            self.assertIn('quarantined_high_memory',(Path(d)/'high-memory-exceptions.jsonl').read_text())
    def test_repeated_pressure_does_not_force_cooldown(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'PAPER_OOM_EVENT_FILES':''}):
            g=ResourceGuard(d)
            for i in range(3):g.quarantine({'id':str(i),'paper_id':'p'}, '[memory_pressure] low')
            self.assertFalse(g.path.exists())
            self.assertIn('"cooldown": 0',g.pressure_path.read_text())

    def test_old_five_minute_wait_is_ignored(self):
        import json
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ, {'PAPER_OOM_EVENT_FILES':''}):
            g=ResourceGuard(d);g.pressure_path.write_text(json.dumps({'last':100,'cooldown':300}))
            with patch('psutil.virtual_memory',return_value=SimpleNamespace(available=3000*1024**2)):
                with patch('time.time',return_value=101):self.assertTrue(g.check())
                with patch('time.time',return_value=111):self.assertFalse(g.check())
    def test_early_isolation_requires_sustained_pressure(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'memory.current';p.write_text(str(2350*1024**2))
            with patch.dict(os.environ,{'PAPER_OOM_EVENT_FILES':'','PAPER_WORKER_MEMORY_CURRENT':str(p)}),patch('psutil.virtual_memory',return_value=SimpleNamespace(available=1100*1024**2)):
                g=ResourceGuard(d)
                with patch('time.monotonic',return_value=10):self.assertFalse(g.check(True))
                with patch('time.monotonic',return_value=12):self.assertIn('提前隔离',g.check(True))
