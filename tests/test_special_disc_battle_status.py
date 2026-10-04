import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from special_disc.writeback.battle_status import apply_status_labels, verify_status_labels
from special_disc.writeback.battle_prompts import apply_prompt_labels, verify_prompt_labels
from special_disc.writeback.battle_titles import apply_title_labels, verify_title_labels
from srwz.iso9660 import scan_iso9660, member_map
from srwz.psmt4 import unswizzle_psmt4, swizzle_psmt4


class SpecialDiscBattleStatusTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        inventory = json.loads((ROOT / 'config/products/special-disc/disc-inventory.json').read_text())
        iso = ROOT / inventory['sp']['path']
        member = member_map(scan_iso9660(iso))['BTL/TRICMN.BIN']
        with iso.open('rb') as stream:
            stream.seek(member.extent_lba * 2048)
            cls.source = stream.read(member.size)

    def test_migration_changes_only_ten_text_rectangles_and_is_idempotent(self):
        output, receipt = apply_status_labels(self.source)
        self.assertEqual(len(output), len(self.source))
        self.assertEqual(output[:290000], self.source[:290000])
        self.assertEqual(output[355536:], self.source[355536:])
        before = unswizzle_psmt4(self.source[290000:355536], 512, 256, row_major_pages=True)
        after = unswizzle_psmt4(output[290000:355536], 512, 256, row_major_pages=True)
        self.assertEqual(len(receipt['labels']), 10)
        self.assertGreater(receipt['changed_texels'], 0)
        # Include arrows and the rest of the atlas in the protected area.
        for i, (a, b) in enumerate(zip(before, after)):
            if i % 512 < 399 or i // 512 >= 240:
                self.assertEqual(a, b)
        repeated, second = apply_status_labels(output)
        self.assertEqual(repeated, output)
        self.assertEqual(second['changed_texels'], 0)
        self.assertEqual(verify_status_labels(output)['labels'], receipt['labels'])

    def test_prompt_migration_preserves_en_status_and_all_other_cells(self):
        source, _ = apply_status_labels(self.source)
        output, receipt = apply_prompt_labels(source)
        self.assertEqual(output[:290000], source[:290000])
        self.assertEqual(output[355536:], source[355536:])
        before = unswizzle_psmt4(source[290000:355536], 512, 256, row_major_pages=True)
        after = unswizzle_psmt4(output[290000:355536], 512, 256, row_major_pages=True)
        config = json.loads((ROOT / 'config/assets/tricmn-battle-overlays-zh.json').read_text())
        owned = set()
        for label in config['labels']:
            if label['render_profile'] in ('prompt', 'prompt-long', 'reason'):
                x, y, w, h = label['rect']
                owned.update((y+j)*512+x+i for j in range(h) for i in range(w))
        self.assertTrue(all(a == b or i in owned for i, (a, b) in enumerate(zip(before, after))))
        self.assertGreater(receipt['changed_texels'], 0)
        self.assertEqual(len(verify_prompt_labels(output)['labels']), 10)
        verify_status_labels(output)
        self.assertEqual(apply_prompt_labels(output)[0], output)
        indexes = bytearray(after)
        indexes[0] ^= 1
        corrupted = output[:290000] + swizzle_psmt4(indexes, 512, 256, row_major_pages=True) + output[355536:]
        with self.assertRaisesRegex(ValueError, 'prompt cell readback drift'):
            verify_prompt_labels(corrupted)

    def test_readback_rejects_a_damaged_status_cell(self):
        output, _ = apply_status_labels(self.source)
        indexes = bytearray(unswizzle_psmt4(output[290000:355536], 512, 256, row_major_pages=True))
        indexes[399] ^= 1
        corrupted = output[:290000] + swizzle_psmt4(indexes, 512, 256, row_major_pages=True) + output[355536:]
        with self.assertRaisesRegex(ValueError, 'status cell readback drift'):
            verify_status_labels(corrupted)

    def test_title_migration_preserves_all_other_labels_and_rejects_corruption(self):
        source, _ = apply_status_labels(self.source)
        source, _ = apply_prompt_labels(source)
        output, receipt = apply_title_labels(source)
        self.assertEqual(output[:222624], source[:222624])
        self.assertEqual(output[288160:], source[288160:])
        before = unswizzle_psmt4(source[222624:288160], 512, 256, row_major_pages=True)
        after = unswizzle_psmt4(output[222624:288160], 512, 256, row_major_pages=True)
        config = json.loads((ROOT / 'config/assets/tricmn-battle-overlays-zh.json').read_text())
        owned = set()
        for label in config['labels']:
            if label['picture_index'] == 0:
                x, y, w, h = label['rect']
                owned.update((y+j)*512+x+i for j in range(h) for i in range(w))
        self.assertTrue(all(a == b or i in owned for i, (a, b) in enumerate(zip(before, after))))
        self.assertEqual(before[:60*512], after[:60*512])  # Original digits, HP/EN and symbols.
        self.assertGreater(receipt['changed_texels'], 0)
        self.assertEqual(len(verify_title_labels(output)['labels']), 12)
        verify_status_labels(output)
        verify_prompt_labels(output)
        repeated, second = apply_title_labels(output)
        self.assertEqual(repeated, output)
        self.assertEqual(second['changed_texels'], 0)
        indexes = bytearray(after)
        indexes[140*512+1] ^= 1
        corrupted = output[:222624] + swizzle_psmt4(indexes, 512, 256, row_major_pages=True) + output[288160:]
        with self.assertRaisesRegex(ValueError, 'title cell readback drift'):
            verify_title_labels(corrupted)
