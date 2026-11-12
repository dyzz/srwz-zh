"""Execute the shared draw/measure selector on fullwidth word separators."""
import json
from pathlib import Path
import unittest
from test_library_protagonist_names import run_mips
from tools.srwz.proportional_hooks import metric_selection_subroutine, compact_records
from tools.srwz.proportional_metrics import runtime_table, compact_runtime_table, space_codes

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = json.loads((ROOT / 'shared/text-layout/proportional-metrics.mjs').read_text().split(' = ', 1)[1].rstrip(';\n'))

class FullwidthWordSpaceTests(unittest.TestCase):
    def test_apostrophe_selection_in_emitted_mips(self):
        profile = REGISTRY['profiles']['battle']
        glyphs = {**profile['glyphs'], **profile['punctuation']}
        for text, selected in [("Let's", True), ("It's", True), ("A'B", True),
                               ("'A", False), ("A'", False), ("甲'乙", False)]:
            with self.subTest(text=text):
                raw = b''.join(glyphs.get(ch, {'code':0x9000})['code'].to_bytes(2,'big') for ch in text)
                source, table, code, stop = 0x2000, 0x3000, 0x4000, 0x5000
                ram = bytearray(0x6000); ram[source:source+len(raw)] = raw
                data = runtime_table(profile); ram[table:table+len(data)] = data
                blob = metric_selection_subroutine(source, source+len(raw), table)
                ram[code:code+len(blob)] = blob
                regs = [0]*32; regs[11] = glyphs["'"]['code']
                regs[25] = source+2*text.index("'"); regs[31] = stop
                run_mips(ram, regs, code, stop)
                self.assertEqual(bool(regs[1]), selected)
                if selected:
                    self.assertEqual(ram[regs[1]+1], 4)
                    self.assertEqual(ram[regs[1]+2], profile['punctuation']["'"]['height'])
                self.assertEqual(ram[source:source+len(raw)], raw)

    def test_fullwidth_space_selection_in_emitted_mips(self):
        cases = [('THE　HEAT', [True]), ('Side　3', [True]), ('RX　78', [True]),
                 ('　THE', [False]), ('THE　', [False]), ('THE　　HEAT', [False, False]),
                 ('甲　乙', [False]), ('THE　中文', [False]),
                 ('THE\n　HEAT', [False]), ('CIWS　/　RX-78', [True, True])]
        # 0x8140 from storage-boundary conversion; the release ASCII space code and its
        # surface-safe alias from the story and other encoders.
        # Both record layouts the hooks are generated for: four-byte legacy records and
        # the two-byte records of scene dispatch (space slot at half the offset).
        for compact, space, (scene, profile) in [(c, s, item) for c in (False, True) for s in space_codes() for item in REGISTRY['profiles'].items()]:
            space_slot = 152 if compact else 304
            glyphs = {**profile['glyphs'], **profile['punctuation']}
            def encode(ch):
                code = space if ch == '　' else glyphs[ch]['code'] if ch in glyphs else 0x9000
                return b'\x0a' if ch == '\n' else code.to_bytes(2, 'big')
            for text, expected in cases:
                with self.subTest(compact=compact, space=hex(space), scene=scene, text=text):
                    raw = b''.join(map(encode, text)); source, table, code, stop = 0x2000, 0x3000, 0x4000, 0x5000
                    ram = bytearray(0x6000);ram[source:source+len(raw)] = raw
                    if compact:
                        data = compact_runtime_table(profile)
                        with compact_records():
                            blob = metric_selection_subroutine(source, source+len(raw), table)
                    else:
                        data = runtime_table(profile)
                        blob = metric_selection_subroutine(source, source+len(raw), table)
                    ram[table:table+len(data)] = data
                    ram[code:code+len(blob)] = blob
                    offset = 0;actual = []
                    for ch in text:
                        if ch == '　':
                            regs = [0]*32;regs[11] = space;regs[25] = source+offset;regs[31] = stop
                            run_mips(ram, regs, code, stop)
                            actual.append(regs[1] == table+space_slot)
                            self.assertIn(regs[1], (0, table+space_slot))
                        offset += len(encode(ch))
                    # The spaced-slash path matches only 0x8140 (one menu string uses it,
                    # and the SP code cave has no room for the alias there).
                    if space != 0x8140 and '/' in text:
                        expected = [False] * len(expected)
                    self.assertEqual(actual, expected)
                    self.assertEqual(ram[source:source+len(raw)], raw)
