"""Execute the shared draw/measure selector on fullwidth word separators."""
import json
from pathlib import Path
import unittest
from test_library_protagonist_names import run_mips
from tools.srwz.proportional_hooks import metric_selection_subroutine
from tools.srwz.proportional_metrics import runtime_table

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
                    self.assertEqual(ram[regs[1]+2], 12)
                self.assertEqual(ram[source:source+len(raw)], raw)

    def test_fullwidth_space_selection_in_emitted_mips(self):
        cases = [('THE　HEAT', [True]), ('Side　3', [True]), ('RX　78', [True]),
                 ('　THE', [False]), ('THE　', [False]), ('THE　　HEAT', [False, False]),
                 ('甲　乙', [False]), ('THE　中文', [False]),
                 ('THE\n　HEAT', [False]), ('CIWS　/　RX-78', [True, True])]
        for scene, profile in REGISTRY['profiles'].items():
            glyphs = {**profile['glyphs'], **profile['punctuation']}
            def encode(ch):
                code = 0x8140 if ch == '　' else glyphs[ch]['code'] if ch in glyphs else 0x9000
                return b'\x0a' if ch == '\n' else code.to_bytes(2, 'big')
            for text, expected in cases:
                with self.subTest(scene=scene, text=text):
                    raw = b''.join(map(encode, text)); source, table, code, stop = 0x2000, 0x3000, 0x4000, 0x5000
                    ram = bytearray(0x6000);ram[source:source+len(raw)] = raw
                    data = runtime_table(profile);ram[table:table+len(data)] = data
                    blob = metric_selection_subroutine(source, source+len(raw), table)
                    ram[code:code+len(blob)] = blob
                    offset = 0;actual = []
                    for ch in text:
                        if ch == '　':
                            regs = [0]*32;regs[11] = 0x8140;regs[25] = source+offset;regs[31] = stop
                            run_mips(ram, regs, code, stop)
                            actual.append(regs[1] == table+304)
                            self.assertIn(regs[1], (0, table+304))
                        offset += len(encode(ch))
                    self.assertEqual(actual, expected)
                    self.assertEqual(ram[source:source+len(raw)], raw)
