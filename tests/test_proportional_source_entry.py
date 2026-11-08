"""Run emitted source-bound capture against real EE RAM edges."""
import struct
import unittest
from test_library_protagonist_names import run_mips
from tools.srwz.proportional_scene_dispatch import source_entry

class SourceEntryTests(unittest.TestCase):
    def exercise(self, address, payload, expected):
        ram = bytearray(0x2000000)
        code, state, stop = 0x150000, 0x460000, 0x160000
        blob = source_entry(state, stop, [0, 0])
        ram[code:code+len(blob)] = blob
        if payload is not None:
            ram[address:address+len(payload)] = payload
        regs = [i * 0x10001 for i in range(32)]
        regs[0] = 0; regs[4] = address; regs[29] = 0x1000000
        for i in (1, 11, 12, 24): regs[i] |= 0x123456789ABCDEF << 64
        before = regs.copy()
        run_mips(ram, regs, code, stop)
        self.assertEqual(struct.unpack_from('<II', ram, state), expected)
        self.assertEqual(regs, before)

    def test_dialogue_stack_buffer(self):
        self.exercise(0x1fff7f0, bytes.fromhex('8260826181400a826200'), (0x1fff7f0,0x1fff7fa))

    def test_nul_at_last_ram_byte(self):
        self.exercise(0x1fffffd, bytes.fromhex('826000'), (0x1fffffd,0x2000000))

    def test_unterminated_buffer_stops_before_ram_end(self):
        self.exercise(0x1fffff0, b'\x82'*16, (0,0))

    def test_invalid_source_is_rejected(self):
        for address in (0,0x2000000,0x80000000):
            with self.subTest(address=address):self.exercise(address,None,(0,0))
