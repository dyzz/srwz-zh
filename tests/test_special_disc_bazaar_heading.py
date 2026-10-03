import copy
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from special_disc.writeback.bazaar_heading import CONFIG, apply_bazaar_heading
from special_disc.writeback.title_atlas import positions, sha


class BazaarHeadingTests(unittest.TestCase):
    def fixture(self):
        c = json.loads(CONFIG.read_text())
        atlas = bytes(c['page_end'] + 16)
        c['before_sha256'] = sha(bytes(len(positions(c['rect']))))
        c['container_sha256'] = sha(bytes(c['page_end'] - c['page_start'] - c['image_size']))
        return c, atlas

    def apply(self, c, atlas):
        p = SimpleNamespace(width=256, height=256, image_type=4, offset=0,
                            header_size=c['image_start'], image_size=c['image_size'])
        with patch('special_disc.writeback.bazaar_heading.parse_tim2',
                   return_value=SimpleNamespace(pictures=[p])):
            return apply_bazaar_heading(atlas, c)[0]

    def test_shared_heading_changes_only_its_mask_and_is_idempotent(self):
        c, atlas = self.fixture()
        result = self.apply(c, atlas)
        self.assertEqual(result, self.apply(c, result))
        self.assertNotEqual(result, atlas)
        start = c['page_start'] + c['image_start']
        old = bytes(v for b in atlas[start:start+c['image_size']] for v in (b&15, b>>4))
        new = bytes(v for b in result[start:start+c['image_size']] for v in (b&15, b>>4))
        allowed = set(positions(c['rect']))
        self.assertTrue(all(a == b for i, (a, b) in enumerate(zip(old, new)) if i not in allowed))
        self.assertEqual(atlas[:start], result[:start])
        self.assertEqual(atlas[start+c['image_size']:], result[start+c['image_size']:])

    def test_rejects_wrong_preimage_palette_and_frozen_pixels(self):
        c, atlas = self.fixture()
        for field, message in [('before_sha256', 'preimage'), ('container_sha256', 'CLUT'),
                               ('sha256', 'frozen indices')]:
            bad = copy.deepcopy(c); bad[field] = '0'*64
            with self.assertRaisesRegex(ValueError, message):
                self.apply(bad, atlas)

    def test_shared_snapshot_drift_is_rejected(self):
        c, atlas = self.fixture(); c['shared_render_snapshot']['sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'shared snapshot drift'):
            self.apply(c, atlas)

    def test_heading_does_not_overlap_sp_title_cells(self):
        c = json.loads(CONFIG.read_text())
        title = json.loads((ROOT/'config/assets/special-disc/title-atlas.json').read_text())
        owned = set(positions(c['rect']))
        for cell in title['cells'] + title['retired_cells'] + title['reused_cells']:
            if cell['page'] == 5:
                self.assertTrue(owned.isdisjoint(positions(cell['rect'])))
