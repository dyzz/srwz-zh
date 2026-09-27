"""Reconstructible SP inputs and the single-current output contract."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from special_disc import baselines
from special_disc.source import CURRENT_ISO


@unittest.skipUnless(shutil.which('xdelta3'), 'requires xdelta3')
class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.source = self.directory/'original.bin'
        self.source.write_bytes(bytes(range(256))*512)
        self.edited = self.directory/'translated.bin'
        data = bytearray(self.source.read_bytes());data[101:111]=b'0123456789'
        self.edited.write_bytes(data)
        self.patches = [patch.object(baselines, 'DIRECTORY', self.directory/'inputs'),
                        patch.object(baselines, 'ISO_TEMP_DIRECTORY', self.directory/'build/iso/.tmp/baselines'),
                        patch.object(baselines, 'SOURCE_ISO', self.source),
                        patch.object(baselines, '_CACHE', {})]
        for item in self.patches:
            item.start();self.addCleanup(item.stop)

    def freeze(self):
        return baselines.freeze_baseline('text-canary', self.edited, source=self.source)

    def test_roundtrip_and_process_cache(self):
        lock = self.freeze()
        self.edited.unlink()
        restored = baselines.baseline_iso('text-canary')
        self.assertEqual(baselines.digest(restored), json.loads(lock.read_text())['iso_sha256'])
        self.assertEqual(baselines.baseline_iso('text-canary'), restored)
        self.assertNotEqual(restored, CURRENT_ISO)
        self.assertTrue(restored.is_relative_to(baselines.ISO_TEMP_DIRECTORY))

    def test_changed_source_fails_closed(self):
        self.freeze();self.source.write_bytes(b'wrong')
        with self.assertRaisesRegex(ValueError, 'patch/source hash drift'):
            baselines.baseline_iso('text-canary')

    def test_corrupt_delta_fails_closed(self):
        self.freeze();(baselines.DIRECTORY/'text-canary.xdelta').write_bytes(b'wrong')
        with self.assertRaisesRegex(ValueError, 'patch/source hash drift'):
            baselines.baseline_iso('text-canary')

    def test_exported_baseline_is_shared_only_with_exact_identity(self):
        lock = self.freeze()
        exported = self.directory/'shared.iso'
        exported.write_bytes(self.edited.read_bytes())
        with patch.dict(baselines.os.environ, {baselines.environment_name('text-canary'): str(exported)}):
            self.assertEqual(baselines.baseline_iso('text-canary'), exported)
        baselines._CACHE.clear()
        exported.write_bytes(b'not the baseline')
        with patch.dict(baselines.os.environ, {baselines.environment_name('text-canary'): str(exported)}):
            with self.assertRaisesRegex(ValueError, 'exported SP baseline identity drift'):
                baselines.baseline_iso('text-canary')
        baselines._CACHE.clear()
        restored = baselines.export_baseline('text-canary')
        self.assertEqual(baselines.os.environ.pop(baselines.environment_name('text-canary')), str(restored))
        self.assertEqual(baselines.digest(restored), json.loads(lock.read_text())['iso_sha256'])

    def test_unknown_baseline_rejected(self):
        with self.assertRaisesRegex(ValueError, 'unknown SP baseline'):
            baselines.baseline_iso('../arbitrary')


class CurrentOutputTests(unittest.TestCase):
    def test_only_current_sp_iso_is_retained(self):
        if not CURRENT_ISO.exists():
            self.skipTest('local SP current ISO is not installed')
        self.assertEqual(sorted(CURRENT_ISO.parent.rglob('*.iso')), [CURRENT_ISO])
        manifest = json.loads(CURRENT_ISO.with_suffix('.json').read_text())
        self.assertEqual(manifest['iso']['path'], str(CURRENT_ISO.relative_to(ROOT)))
        self.assertEqual(manifest['iso']['size'], CURRENT_ISO.stat().st_size)


if __name__ == '__main__':
    unittest.main()
