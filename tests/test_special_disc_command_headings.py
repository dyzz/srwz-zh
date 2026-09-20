import copy
import json
import struct
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from special_disc.writeback.command_headings import CONFIG, apply_command_headings, sha


class CommandHeadingTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(CONFIG.read_text())

    def test_all_sp_command_variants_are_rectangular_one_to_one_and_keep_native_colours(self):
        cells = {c['id']: c['rect'] for c in self.config['cells']}
        chunks = set()
        for p in self.config['patches']:
            old, new = bytes.fromhex(p['native_hex']), bytes.fromhex(p['after_hex'])
            if len(new) == 16:
                self.assertEqual(old[:8], new[:8])
                continue
            chunks.add(p['chunk'])
            self.assertEqual(old[:4], new[:4])
            self.assertEqual(old[4] & 0xf0, new[4] & 0xf0)
            self.assertEqual(old[5:10], new[5:10])
            if p.get('operation') == 'collapse':
                self.assertEqual(new[10:30], bytes(20))
                continue
            if p.get('operation') == 'retarget_uv':
                self.assertEqual(new[:30], old[:30])
                self.assertEqual(new[32] - new[30], old[32] - old[30])
                continue
            x, y, w, h = cells[p['token']]
            self.assertEqual(new[30:], bytes((x, y, x + w, y + h)))
            v = struct.unpack('<10h', new[10:30])
            self.assertEqual(v[2], v[4])
            self.assertEqual(v[6], v[8])
            self.assertEqual(v[6] - v[4], w)
            self.assertEqual(2 * (v[5] - v[3]), h)
        self.assertEqual(chunks, {150, 151, 152, 153, 162, 163, 164, 165, 167, 168, 169, 171, 1085})
        formation = [p for p in self.config['patches'] if p['token'] == 'formation']
        self.assertEqual(len(formation), 29)
        for p in formation:
            data = bytes.fromhex(p['after_hex'])
            self.assertEqual(data[4] & 15, 4)
            self.assertNotEqual(data[30:], bytes((160, 56, 198, 72)))

    def test_support_window_has_one_centred_title_and_reserves_shared_texture(self):
        records = [p for p in self.config['patches'] if p['chunk'] == 164]
        self.assertEqual(len(records), 6)
        visible = [p for p in records if p.get('operation') != 'collapse']
        self.assertEqual([p['token'] for p in visible], ['command', 'command'])
        self.assertEqual([struct.unpack('<2h', bytes.fromhex(p['after_hex'])[10:14])
                          for p in visible], [(50, 7), (48, 6)])
        for p in records:
            if p['token'] == 'separator':
                self.assertEqual(bytes.fromhex(p['after_hex'])[8:], bytes(8))
        self.assertEqual(self.config['support_texture_reservation']['status'], 'shared_do_not_reuse')
        self.assertEqual(self.config['page']['index'], 4)

    def test_setup_title_crop_contains_all_four_chinese_characters(self):
        records = [p for p in self.config['patches'] if p['token'] == 'intermission']
        self.assertEqual(len(records), 2)
        for p in records:
            old, new = bytes.fromhex(p['native_hex']), bytes.fromhex(p['after_hex'])
            self.assertGreater(old[30], 57)  # Native suffix crop clips the Chinese ink.
            self.assertLessEqual(new[30], 57)
            self.assertGreaterEqual(new[32], 159)
            self.assertEqual(new[:30], old[:30])

    def test_only_owned_indices_and_records_change_and_repeat_is_identical(self):
        config = copy.deepcopy(self.config)
        chunk = b'HEADER' + bytes(32768) + b'CLUT-and-trailing'
        atlas = b'prefix' + chunk + b'suffix'
        config['atlas_size'] = len(atlas)
        config['page'] = dict(start=6, end=6 + len(chunk), container_sha256=sha(chunk[:6] + chunk[32774:]))
        owned = set()
        for c in config['cells']:
            x, y, w, h = c['rect']
            c['before_sha256'] = sha(bytes(w*h))
            owned.update(yy*256+xx for yy in range(y,y+h) for xx in range(x,x+w))
        drawings = bytearray(b'\xa5' * config['drawings_size'])
        byte_owned = set()
        for p in config['patches']:
            old = bytes.fromhex(p['before_hex']); off = p['offset']
            drawings[off:off+len(old)] = old
            byte_owned.update(range(off, off+len(old)))
        picture = SimpleNamespace(width=256,height=256,image_type=4,offset=0,header_size=6,image_size=32768)
        with patch('special_disc.writeback.command_headings.parse_tim2', return_value=SimpleNamespace(pictures=[picture])):
            out, draw, _ = apply_command_headings(atlas,bytes(drawings),config)
            self.assertEqual(apply_command_headings(out,draw,config)[:2],(out,draw))
            self.assertEqual(out[:12],atlas[:12])
            self.assertEqual(out[32780:],atlas[32780:])
            idx = bytes(v for b in out[12:32780] for v in (b&15,b>>4))
            self.assertTrue(all(idx[i]==0 for i in range(65536) if i not in owned))
            self.assertTrue(all(draw[i]==drawings[i] for i in range(len(draw)) if i not in byte_owned))
            broken = bytearray(drawings); broken[config['patches'][0]['offset']+6] ^= 1
            with self.assertRaisesRegex(ValueError,'preimage'):
                apply_command_headings(atlas,bytes(broken),config)
            config['patches'][0]['after_hex'] = 'ff' + config['patches'][0]['after_hex'][2:]
            with self.assertRaisesRegex(ValueError,'flags/material/colour'):
                apply_command_headings(atlas,bytes(drawings),config)


if __name__ == '__main__':
    unittest.main()
