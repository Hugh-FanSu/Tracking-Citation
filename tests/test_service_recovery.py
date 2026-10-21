import tempfile,unittest,os
from unittest.mock import patch,Mock
from paper_citation_pipeline.ledger.service_recovery import ServiceRecovery
class RecoveryTests(unittest.TestCase):
    def test_wait_restart_then_stable(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'PAPER_GROBID_RESTART_COMMAND':'["true"]'}):
            guard=Mock();r=ServiceRecovery(d,guard)
            with patch('time.time',return_value=100):self.assertTrue(r.check(False))
            with patch('time.time',return_value=221),patch('subprocess.run') as run:
                run.return_value.returncode=0;r.check(False);run.assert_called_once()
            with patch('time.time',return_value=225):self.assertTrue(r.check(True))
            with patch('time.time',return_value=256):self.assertFalse(r.check(True))
            self.assertFalse(r.path.exists());guard.trip.assert_not_called()
    def test_restart_is_bounded(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'PAPER_GROBID_RESTART_COMMAND':'["true"]'}),patch('subprocess.run') as run:
            run.return_value.returncode=1;guard=Mock();r=ServiceRecovery(d,guard)
            for t in [0,121,242,363,484]:
                with patch('time.time',return_value=t):r.check(False)
            self.assertEqual(run.call_count,3);guard.trip.assert_called_once()
