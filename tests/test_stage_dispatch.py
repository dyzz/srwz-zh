from pathlib import Path
import json
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from srwz.edition import EditionError
from srwz.stage_dispatch import (BEST_BASE, ORIGINAL_BASE, PATTERN, check_shared_tail,
                                 dispatchers, relocate_dispatch, verify_dispatch)


class StageDispatchTests(unittest.TestCase):
    def fixture(self, index):
        config = json.loads((Path(__file__).resolve().parents[1] / 'config/editions/best/source-layout.json').read_text())
        spec = config['stage_layouts'][str(index)]['event_dispatch']
        original = bytearray(spec['original_table'] + 48)
        native = bytearray(original)
        for data, base, table in ((original, ORIGINAL_BASE, spec['original_table']),
                                  (native, BEST_BASE, spec['best_table'])):
            address = base + table
            struct.pack_into('<6I', data, spec['instruction_offset'],
                             0x3C040000 | ((address+0x8000) >> 16),
                             0x24840000 | (address & 65535), *PATTERN)
            struct.pack_into('<10I', data, table, *[base + 0x100 + i*4 for i in range(10)])
        return original, native, spec

    def test_both_layouts_preserve_text_and_relocate_every_target(self):
        for index in (111, 150):
            with self.subTest(index=index):
                original, native, spec = self.fixture(index)
                start, end = 0x1000, spec['original_table']
                check_shared_tail(original, native, original, spec, start, [(start,end)])
                output = bytearray(native)
                output[start:end] = b'Z' * (end-start)
                before = bytes(output)
                relocate_dispatch(output, native, spec)
                proof = verify_dispatch(native, output, spec)
                self.assertEqual(output[start:end], before[start:end])
                self.assertEqual(proof[0]['table_offset'], end)
                self.assertEqual(proof[0]['targets'], dispatchers(native)[0]['targets'])
                # Stage 111 requires the signed-low carry; stage 150 does not.
                self.assertEqual(len(proof[0]['targets']), 10)

    def test_stale_consumer_and_each_wrong_target_rejected(self):
        for index in (111, 150):
            original, native, spec = self.fixture(index)
            output = bytearray(native)
            relocate_dispatch(output, native, spec)
            site = spec['instruction_offset']
            broken = bytearray(output)
            broken[site:site+8] = native[site:site+8]
            with self.assertRaises(EditionError):
                verify_dispatch(native, broken, spec)
            for event in range(10):
                with self.subTest(index=index,event=event):
                    broken = bytearray(output)
                    offset = spec['original_table'] + event*4
                    broken[offset:offset+4] = original[offset:offset+4]
                    with self.assertRaises(EditionError):
                        verify_dispatch(native, broken, spec)

    def test_unknown_preimage_and_text_overlap_rejected(self):
        original, native, spec = self.fixture(111)
        end = spec['original_table']
        with self.assertRaisesRegex(EditionError, 'text overlaps'):
            check_shared_tail(original, native, original, spec, 0x1000, [(0x1000,end+1)])
        compiled = bytearray(original)
        compiled[end] ^= 4
        with self.assertRaisesRegex(EditionError, 'shared compiler'):
            check_shared_tail(original, native, compiled, spec, 0x1000, [(0x1000,end)])
        native[spec['best_table']] ^= 4
        with self.assertRaisesRegex(EditionError, 'target preimage'):
            check_shared_tail(original, native, original, spec, 0x1000, [(0x1000,end)])

    def test_undeclared_dispatch_changes_are_rejected(self):
        _, native, spec = self.fixture(150)
        self.assertEqual(len(verify_dispatch(native, native)), 1)
        output = bytearray(native)
        relocate_dispatch(output, native, spec)
        with self.assertRaises(EditionError):
            verify_dispatch(native, output)
        output = bytearray(native)
        output[spec['instruction_offset']+8] ^= 1
        with self.assertRaises(EditionError):
            verify_dispatch(native, output)


if __name__ == '__main__':
    unittest.main()
