"""Version glyphs must preserve source artwork, palette and all other records."""
from pathlib import Path
import base64
import copy
import json
import unittest
import zlib
import sys
import tempfile
from unittest.mock import patch

from tools.srwz.codec import decode
from tools.srwz.tim2 import scan_tim2
from tools.srwz.title_menu import TitleMenuError, build_title_menu
from tools.freeze_title_version import freeze, version_text

ROOT = Path(__file__).resolve().parents[1]


class TitleVersionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = ROOT / 'work/disc/DATA/VT1.BIN'
        if not source.is_file():
            raise unittest.SkipTest('original VT1 member is unavailable')
        with source.open('rb') as f:
            f.seek(0xA751B0)
            cls.source = decode(f.read(0x72560)).output
        cls.contract = json.loads((ROOT / 'config/assets/title-menu-zh.json').read_text())

    def test_badge_changes_only_frozen_glyph_pixels(self):
        baseline_contract = copy.deepcopy(self.contract)
        badge = baseline_contract.pop('version_badge')
        baseline = build_title_menu(self.source, baseline_contract)
        edited = build_title_menu(self.source, self.contract)
        p = scan_tim2(self.source)[2].pictures[0]
        x, y, width, height = badge['rectangle']
        mask = zlib.decompress(base64.b64decode(badge['mask_zlib_base64']))
        permitted = {p.offset + p.header_size + (y + i // width)*640 + x + i % width
                     for i, value in enumerate(mask) if value}
        changes = {i for i, (a, b) in enumerate(zip(baseline.data, edited.data)) if a != b}
        self.assertTrue(changes)
        self.assertTrue(changes <= permitted)
        self.assertEqual(len(edited.data), len(self.source))
        self.assertEqual(scan_tim2(edited.data), scan_tim2(self.source))
        self.assertEqual(edited.changed_pixel_count, baseline.changed_pixel_count)
        self.assertEqual(edited.version_badge['changed_pixel_count'], len(changes))
        self.assertEqual(edited.version_badge['text'], badge['text'])

    def test_background_and_mask_drift_are_rejected(self):
        changed = bytearray(self.source)
        p = scan_tim2(self.source)[2].pictures[0]
        changed[p.offset + p.header_size] ^= 1
        with self.assertRaises(TitleMenuError):
            build_title_menu(bytes(changed), self.contract)
        changed_contract = copy.deepcopy(self.contract)
        changed_contract['version_badge']['mask_sha256'] = '0' * 64
        with self.assertRaisesRegex(TitleMenuError, 'mask contract drift'):
            build_title_menu(self.source, changed_contract)

    def test_tagged_release_and_untagged_date_labels(self):
        with patch('tools.freeze_title_version.subprocess.check_output', return_value='v0.5.0\n'):
            self.assertEqual(version_text(ROOT, date='20261004', release_tag='v0.4.2'), 'v0.5.0')
        with patch('tools.freeze_title_version.subprocess.check_output', return_value=''):
            self.assertEqual(version_text(ROOT, date='20261004', release_tag='v0.4.2'), 'v0.4.2+20261004')
            with self.assertRaises(ValueError):
                version_text(ROOT, date='2026-10-04', release_tag='v0.4.2')
        with patch('tools.freeze_title_version.subprocess.check_output', side_effect=['', FileNotFoundError('gh')]):
            self.assertEqual(version_text(ROOT, date='20261004'),
                             self.contract['version_badge']['latest_release_tag'] + '+20261004')

    def test_frozen_glyphs_render_without_a_system_font(self):
        badge = freeze(self.contract['version_badge']['text'], root=ROOT)
        self.assertEqual(badge['authoring']['size_px'], 10)
        self.assertEqual(badge, self.contract['version_badge'])
        formal = freeze('v0.5.0', root=ROOT)
        self.assertEqual(formal['text'], 'v0.5.0')
        self.assertNotEqual(formal['output_image_sha256'], freeze('v0.5.1', root=ROOT)['output_image_sha256'])

    def test_fresh_checkout_reads_title_source_from_original_iso(self):
        iso = ROOT / 'rom/original.iso'
        if not iso.is_file():
            self.skipTest('original disc is unavailable')
        original_is_file = Path.is_file
        member = ROOT / 'work/disc/DATA/VT1.BIN'
        def is_file(path):
            return False if path == member else original_is_file(path)
        with patch.object(Path, 'is_file', is_file):
            self.assertEqual(freeze(self.contract['version_badge']['text'], root=ROOT),
                             self.contract['version_badge'])

    def test_release_freeze_rejects_a_date_badge(self):
        with patch.object(sys, 'path', [str(ROOT / 'tools'), *sys.path]):
            import freeze_release
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = root / 'inputs/project/config/assets/title-menu-zh.json'
            inputs.parent.mkdir(parents=True)
            inputs.write_text(json.dumps({'version_badge': {'text': 'v0.4.2+20261004'}}))
            batch = root / 'batch.json'
            batch.write_text(json.dumps({'input_snapshot': 'inputs/inputs.json'}))
            with patch.object(freeze_release, 'ROOT', root), patch.object(
                freeze_release, 'verify_batch', return_value={'verified_editions': ['original', 'best', 'sp']}):
                with self.assertRaisesRegex(ValueError, 'rebuild with --release-version 0.5.0'):
                    freeze_release.freeze(batch, '0.5.0', xdelta={})
            self.assertFalse((root / 'build/iso/v0.5.0').exists())


if __name__ == '__main__':
    unittest.main()
