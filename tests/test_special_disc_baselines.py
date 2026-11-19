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

    def test_view_reuses_only_verified_delta_and_materialized_bytes(self):
        directory = self.directory / 'cache'
        with patch.dict(baselines.os.environ, {baselines.view_cache.ENV: str(directory)}):
            self.freeze()
            with patch.object(baselines.subprocess, 'run', wraps=baselines.subprocess.run) as command:
                self.freeze()
                self.assertFalse(any(call.args[0][1] in ('-e', '-d') for call in command.call_args_list))
                edited = self.edited.read_bytes() + b'changed'
                self.edited.write_bytes(edited)
                self.freeze()
                self.assertTrue(any(call.args[0][1] == '-e' for call in command.call_args_list))
            cached = baselines.baseline_iso('text-canary')
            self.assertEqual(cached.read_bytes(), edited)
            cached.write_bytes(b'wrong')
            baselines._CACHE.clear()
            self.assertEqual(baselines.baseline_iso('text-canary').read_bytes(), edited)
            (directory / 'text-canary.delta').write_bytes(b'wrong')
            with patch.object(baselines.subprocess, 'run', wraps=baselines.subprocess.run) as command:
                self.freeze()
                self.assertTrue(any(call.args[0][1] == '-d' for call in command.call_args_list))

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

    def test_sparse_sidecar_replaces_delta_restore(self):
        lock = self.freeze()
        self.edited.unlink()
        first = baselines.baseline_iso('text-canary')
        meta_path, data_path = baselines._sparse_paths('text-canary')
        meta = json.loads(meta_path.read_text())
        self.assertEqual(meta['iso_sha256'], json.loads(lock.read_text())['iso_sha256'])
        self.assertEqual(meta['spans'], [[0, 65536]])
        self.assertEqual(sum(length for _, length in meta['spans']), data_path.stat().st_size)
        self.assertLess(data_path.stat().st_size, self.source.stat().st_size)
        # The delta is no longer needed once the sidecar exists.
        (baselines.DIRECTORY/'text-canary.xdelta').unlink()
        baselines._CACHE.clear()
        second = baselines.baseline_iso('text-canary')
        self.assertNotEqual(first, second)
        self.assertEqual(baselines.digest(second), meta['iso_sha256'])
        self.assertEqual(second.read_bytes()[101:111], b'0123456789')

    def test_corrupt_sparse_sidecar_falls_back_to_delta(self):
        self.freeze()
        baselines.baseline_iso('text-canary')
        meta_path, data_path = baselines._sparse_paths('text-canary')
        data_path.write_bytes(b'x' * data_path.stat().st_size)
        baselines._CACHE.clear()
        restored = baselines.baseline_iso('text-canary')
        self.assertEqual(restored.read_bytes(), self.edited.read_bytes())
        self.assertEqual(baselines.digest(data_path), json.loads(meta_path.read_text())['data_sha256'])
        stale = json.loads(meta_path.read_text()); stale['iso_sha256'] = '0' * 64
        meta_path.write_text(json.dumps(stale))
        baselines._CACHE.clear()
        self.assertEqual(baselines.baseline_iso('text-canary').read_bytes(), self.edited.read_bytes())
        self.assertNotEqual(json.loads(meta_path.read_text())['iso_sha256'], '0' * 64)

    def test_unknown_baseline_rejected(self):
        with self.assertRaisesRegex(ValueError, 'unknown SP baseline'):
            baselines.baseline_iso('../arbitrary')


class ViewCacheTests(unittest.TestCase):
    def test_only_the_payload_bound_to_the_current_inputs_is_accepted(self):
        cache = baselines.view_cache
        with tempfile.TemporaryDirectory() as directory:
            slot = Path(directory) / 'atlas.texture'
            key = cache.cache_key({'pixels': 'a', 'table': [0, 64]})
            other = cache.cache_key({'pixels': 'a', 'table': [0, 48]})
            cache.write_entry(slot, key, b'first')
            self.assertEqual(cache.read_entry(slot, key), b'first')
            self.assertIsNone(cache.read_entry(slot, other))
            cache.write_entry(slot, other, b'second')
            self.assertIsNone(cache.read_entry(slot, key))
            slot.write_bytes(slot.read_bytes()[:-1] + b'!')
            self.assertIsNone(cache.read_entry(slot, other))


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
