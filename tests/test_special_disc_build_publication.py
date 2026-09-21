"""A failed rebuild must not invalidate the last verified SP artifacts."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'tools/special_disc/writeback')]
import build_full_text as build
from write_frame_text import publish_component


class ComponentPublicationTests(unittest.TestCase):
    def test_failed_attempt_preserves_previous_report_and_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)/'frame'; out.mkdir()
            (out/'report.json').write_bytes(b'previous verified report')
            (out/'binary').write_bytes(b'previous verified component')
            self.assertFalse(publish_component(out, {'status': 'failed', 'failures': ['overflow']},
                                               {'binary': b'partial new component'}))
            self.assertEqual((out/'report.json').read_bytes(), b'previous verified report')
            self.assertEqual((out/'binary').read_bytes(), b'previous verified component')
            self.assertEqual(json.loads((out.parent/'frame.failed.json').read_text())['failures'], ['overflow'])

    def test_success_replaces_the_complete_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)/'frame'; out.mkdir()
            (out/'obsolete').write_bytes(b'old')
            self.assertTrue(publish_component(out, {'status': 'static_verified_runtime_pending'},
                                              {'DATA/VT1.BIN': b'new'}))
            self.assertFalse((out/'obsolete').exists())
            self.assertEqual((out/'DATA/VT1.BIN').read_bytes(), b'new')
            self.assertEqual(json.loads((out/'report.json').read_text())['status'], 'static_verified_runtime_pending')


class IsoPublicationTests(unittest.TestCase):
    def test_failure_and_concurrent_update_do_not_replace_current(self):
        for mode in ('verify-fails', 'concurrent-update', 'success'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); out = root/'current.iso'; candidate = root/'candidate.iso'
                out.write_bytes(b'old ISO'); out.with_suffix('.json').write_bytes(b'old receipt')
                candidate.write_bytes(b'new ISO')
                def verifier(*args, **kwargs):
                    # The old generation must remain intact while verification runs.
                    self.assertEqual(out.read_bytes(), b'old ISO')
                    self.assertEqual(out.with_suffix('.json').read_bytes(), b'old receipt')
                    if mode == 'verify-fails':
                        raise subprocess.CalledProcessError(1, args[0])
                    (root/'independent-readback.json').write_text('{}')
                    if mode == 'concurrent-update':
                        out.with_suffix('.json').write_bytes(b'another writer')
                with patch.object(build, 'ROOT', root), patch.object(build.subprocess, 'run', side_effect=verifier):
                    call = lambda: build.verify_and_publish(candidate, out, root, {}, build.sha(b'old ISO'), b'old receipt')
                    if mode == 'success':
                        call()
                        self.assertEqual(out.read_bytes(), b'new ISO')
                        self.assertIn('independent_readback', json.loads(out.with_suffix('.json').read_text()))
                    else:
                        with self.assertRaises(subprocess.CalledProcessError if mode == 'verify-fails' else ValueError):
                            call()
                        self.assertEqual(out.read_bytes(), b'old ISO')
                        self.assertEqual(out.with_suffix('.json').read_bytes(), b'old receipt' if mode == 'verify-fails' else b'another writer')
                self.assertFalse(candidate.exists())
                self.assertFalse(candidate.with_suffix('.json').exists())


if __name__ == '__main__':
    unittest.main()
