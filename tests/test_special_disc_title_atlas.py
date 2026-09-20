import copy
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from special_disc.writeback.title_atlas import CONFIG, apply_title_atlas, decode, positions, sha


class SpecialDiscTitleAtlasTests(unittest.TestCase):
    def fixture(self):
        c = json.loads(CONFIG.read_text())
        atlas = bytes(c['atlas_size'])
        drawings = bytearray(c['drawings_size'])
        for p in c['pages']:
            p['container_sha256'] = sha(bytes(p['end'] - p['start'] - p['image_size']))
        for r in c['reused_cells']:
            r['sha256'] = sha(bytes(r['rect'][2] * r['rect'][3]))
        for p in c['patches']:
            raw = bytes.fromhex(p['before_hex'])
            drawings[p['offset']:p['offset'] + len(raw)] = raw
        for r in c['number_protection']:
            r['sha256'] = sha(drawings[r['start']:r['end']])
        c['number_texture_protection']['sha256'] = sha(bytes(256 * 56))
        return c, atlas, bytes(drawings)

    def run_writer(self, c, a, k):
        picture = SimpleNamespace(width=256, height=256, image_type=4, offset=0,
                                  header_size=64, image_size=32768)
        with patch('special_disc.writeback.title_atlas.parse_tim2', return_value=SimpleNamespace(pictures=[picture])):
            return apply_title_atlas(a, k, c)

    def test_only_declared_pixels_and_records_change_and_repeat_is_identical(self):
        c, a, k = self.fixture()
        aa, kk, _ = self.run_writer(c, a, k)
        self.assertEqual(self.run_writer(c, aa, kk)[:2], (aa, kk))
        pages = {p['index']:p for p in c['pages']}
        allowed_atlas = set()
        for cell in c['cells']:
            start = pages[cell['page']]['start'] + pages[cell['page']]['image_start']
            allowed_atlas.update(start + i // 2 for i in positions(cell['rect']))
        self.assertTrue(all(x == y for i, (x, y) in enumerate(zip(a, aa)) if i not in allowed_atlas))
        allowed_draw = set()
        for p in c['patches']:
            allowed_draw.update(range(p['offset'], p['offset'] + len(bytes.fromhex(p['before_hex']))))
        self.assertTrue(all(x == y for i, (x, y) in enumerate(zip(k, kk)) if i not in allowed_draw))

    def test_protected_uv_and_wrong_preimages_fail_closed(self):
        c, a, k = self.fixture()
        first = c['cells'][0]
        broken = copy.deepcopy(c)
        first_pos = positions(first['rect'])[0]
        import base64, zlib
        mask = bytearray(65536); mask[first_pos] = 1
        next(r for r in broken['source_reservations'] if r['page'] == first['page'])['occupied_mask_zlib_base64'] = base64.b64encode(zlib.compress(mask)).decode()
        with self.assertRaisesRegex(ValueError, 'protected source'):
            self.run_writer(broken, a, k)
        bad = bytearray(k); bad[c['patches'][0]['offset'] + 6] ^= 1
        with self.assertRaisesRegex(ValueError, 'preimage'):
            self.run_writer(c, a, bytes(bad))
        broken = copy.deepcopy(c)
        p = broken['patches'][0]; raw = bytearray.fromhex(p['after_hex']); raw[6] ^= 1; p['after_hex'] = raw.hex()
        with self.assertRaisesRegex(ValueError, 'colour'):
            self.run_writer(broken, a, k)

    def test_shared_slot_clut_is_rejected_and_deferred_effects_are_excluded(self):
        c, a, k = self.fixture()
        p = next(p for p in c['patches'] if p['operation'] == 'retarget' and bytes.fromhex(p['after_hex'])[4] & 15 == 8)
        # Texture 8 + CLUT 6 collide in slot 5, even though they are distinct pages.
        for field in ('before_hex','after_hex'):
            raw = bytearray.fromhex(p[field]); raw[4] = 0x60 | (raw[4] & 15); p[field] = raw.hex()
        k = bytearray(k); k[p['offset']:p['offset'] + len(bytes.fromhex(p['before_hex']))] = bytes.fromhex(p['before_hex'])
        with self.assertRaisesRegex(ValueError, 'slot collision'):
            self.run_writer(c, a, bytes(k))
        self.assertTrue(set(p['chunk'] for p in c['patches']).isdisjoint(c['deferred_chunks']))

    def test_strip_gutters_reconstruct_neighbouring_samples_without_seams(self):
        c = json.loads(CONFIG.read_text())
        for word in {r['word'] for r in c['cells']}:
            cells = [r for r in c['cells'] if r['word'] == word]
            w = max(r['source_rect'][0] + r['source_rect'][2] for r in cells)
            h = max(r['source_rect'][1] + r['source_rect'][3] for r in cells)
            px, covered = bytearray(w*h), set()
            for r in cells:
                sx, sy, cw, ch = r['source_rect']; raw = decode(r['indices_zlib_base64']); stride = cw+2
                for y in range(ch):
                    for x in range(cw):
                        i = (sy+y)*w+sx+x
                        self.assertNotIn(i, covered); covered.add(i); px[i] = raw[(y+1)*stride+x+1]
            self.assertEqual(len(covered), w*h)
            self.assertTrue(any(1 <= v <= 7 for v in px))
            self.assertTrue(any(8 <= v <= 15 for v in px))
            for r in cells:
                sx, sy, cw, ch = r['source_rect']; raw = decode(r['indices_zlib_base64'])
                expected = bytes(px[y*w+x] if 0 <= x < w and 0 <= y < h else 0
                                 for y in range(sy-1,sy+ch+1) for x in range(sx-1,sx+cw+1))
                self.assertEqual(raw, expected)

    def test_data_help_uses_main_game_connected_spacing_in_both_colour_passes(self):
        import struct
        c = json.loads(CONFIG.read_text())
        records = [p for p in c['patches'] if p['chunk'] == 1198]
        for group in (records[:8], records[8:]):
            item = next(p for p in group if p['token'] == 'item/0-0')
            help_word = next(p for p in group if p['token'] == 'help')
            left_item = struct.unpack_from('<h', bytes.fromhex(item['after_hex']), 14)[0]
            left_help = struct.unpack_from('<h', bytes.fromhex(help_word['after_hex']), 14)[0]
            self.assertEqual(left_help - left_item, 38)
        def bounds(raw):
            values = struct.unpack('<10h', raw[10:-4])
            return min(values[2::2]), min(values[3::2]), max(values[2::2]), max(values[3::2])
        for t in (t for t in c['titles'] if t['chunk'] == 1198):
            boxes = [bounds(bytes.fromhex(p['after_hex'])) for p in records
                     if p['offset'] in t['record_offsets'] and p['operation'] == 'retarget']
            self.assertEqual(min(b[0] for b in boxes) + max(b[2] for b in boxes),
                             t['alignment']['region'][0] + t['alignment']['region'][2])

    def test_only_data_help_remains_and_other_titles_restore_exact_baseline(self):
        c = json.loads(CONFIG.read_text())
        self.assertEqual({t['chunk'] for t in c['titles']}, {1198})
        self.assertEqual({r['word'] for r in c['cells']}, {'item'})
        self.assertEqual({r['id'] for r in c['reused_cells']}, {'help'})
        restored = [p for p in c['patches'] if p['chunk'] != 1198]
        self.assertEqual(len(restored), 196)
        self.assertTrue(all(p['operation'] == 'restore' and p['after_hex'] == p['before_hex'] for p in restored))
        self.assertEqual(len(c['retired_cells']), 44)

    def test_retired_allocations_are_cleared_without_touching_source_pixels(self):
        c, atlas, drawings = self.fixture()
        atlas = bytearray(atlas)
        pages = {p['index']: p for p in c['pages']}
        retired = set()
        for cell in c['retired_cells']:
            cell['sha256'] = sha(bytes([1]) * (cell['rect'][2] * cell['rect'][3]))
            start = pages[cell['page']]['start'] + pages[cell['page']]['image_start']
            for pixel in positions(cell['rect']):
                offset, shift = start + pixel // 2, (pixel % 2) * 4
                atlas[offset] |= 1 << shift
                retired.add((offset, shift))
        out, _, _ = self.run_writer(c, bytes(atlas), drawings)
        self.assertTrue(all((out[offset] >> shift) & 15 == 0 for offset, shift in retired))
        self.assertEqual(self.run_writer(c, out, drawings)[0], out)

    def test_installed_previous_layout_upgrades_and_subsamples_cannot_escape_cell(self):
        c, atlas, original = self.fixture()
        previous = bytearray(original)
        for p in c['patches']:
            value = bytes.fromhex(p.get('previous_hex', [p['after_hex']])[0])
            previous[p['offset']:p['offset'] + len(value)] = value
        self.assertEqual(self.run_writer(c, atlas, bytes(previous))[:2], self.run_writer(c, atlas, original)[:2])
        broken = copy.deepcopy(c)
        p = next(p for p in broken['patches'] if p['operation'] == 'retarget')
        p['sample_uv'] = [-1, 0, 1, 1]
        with self.assertRaisesRegex(ValueError, 'sample outside'):
            self.run_writer(broken, atlas, original)


if __name__ == '__main__':
    unittest.main()
