"""Execute SP policy instructions, native clear queries, and reward branches."""
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'tools/special_disc/writeback')]
from special_disc.writeback import data_link_bonus as policy

try:
    from unicorn import Uc, UC_ARCH_MIPS, UC_MODE_MIPS64, UC_MODE_LITTLE_ENDIAN, UC_HOOK_CODE
    from unicorn.mips_const import (UC_MIPS_REG_PC, UC_MIPS_REG_RA, UC_MIPS_REG_A0,
        UC_MIPS_REG_V0, UC_MIPS_REG_SP, UC_MIPS_REG_S0, UC_MIPS_REG_S6)
except ImportError:
    Uc = None


class DefaultZBonusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = ROOT/'work/disc/special-disc/SLPS_259.20'
        if not path.exists():
            raise unittest.SkipTest('local original SP executable is not extracted')
        cls.original = path.read_bytes()
        cls.patched = policy.patch_executable(cls.original)

    def test_exact_boundaries_and_idempotence(self):
        allowed = {va-policy.DELTA+i for va, before, _ in policy.SITES for i in range(len(before))}
        changed = {i for i, (a, b) in enumerate(zip(self.original, self.patched)) if a != b}
        self.assertTrue(changed)
        self.assertTrue(changed <= allowed)
        self.assertEqual(len(self.original), len(self.patched))
        self.assertEqual(policy.patch_executable(self.patched), self.patched)
        # Reward table, SP-clear queries, and native application are protected.
        for a, z in [(0x319E30, 0x319EA0), (0x31BD40, 0x31BF44), (0x4A09F0, 0x4A0BD0)]:
            self.assertEqual(self.original[a-policy.DELTA:z-policy.DELTA], self.patched[a-policy.DELTA:z-policy.DELTA])

    def test_context_drift_rejected(self):
        for va in [0x319DD0, 0x319E54, 0x31B7DC, 0x31B810, 0x31B814, 0x31B830]:
            damaged = bytearray(self.original); damaged[va-policy.DELTA] ^= 1
            with self.subTest(va=hex(va)), self.assertRaises(ValueError):
                policy.patch_executable(bytes(damaged))
        with self.assertRaises(ValueError):
            policy.patch_executable(self.original[:-1])

    def machine(self):
        if Uc is None:
            self.skipTest('Unicorn required for native instruction execution')
        u = Uc(UC_ARCH_MIPS, UC_MODE_MIPS64 | UC_MODE_LITTLE_ENDIAN)
        u.mem_map(0, 0x2000000)
        phoff = struct.unpack_from('<I', self.patched, 28)[0]
        stride, count = struct.unpack_from('<HH', self.patched, 42)
        for i in range(count):
            typ, off, va, _, size, *_ = struct.unpack_from('<8I', self.patched, phoff+i*stride)
            if typ == 1 and size:
                u.mem_write(va, self.patched[off:off+size])
        return u

    def run_code(self, u, start, end, query=None):
        calls = []
        def hook(uc, addr, size, data):
            if addr == end:
                uc.emu_stop()
            elif addr == 0x155040 and query is not None:
                event = uc.reg_read(UC_MIPS_REG_A0); calls.append(event)
                uc.reg_write(UC_MIPS_REG_V0, query.get(event, 0))
                uc.reg_write(UC_MIPS_REG_PC, uc.reg_read(UC_MIPS_REG_RA))
            elif addr in (0x440980, 0x4409B0, 0x132C08, 0x1324A8):
                self.fail(f'entered Z memory-card path at {addr:#x}')
        handle = u.hook_add(UC_HOOK_CODE, hook)
        try:
            u.emu_start(start, 0, count=100000)
        finally:
            u.hook_del(handle)
        self.assertEqual(u.reg_read(UC_MIPS_REG_PC), end)
        return calls

    def test_empty_and_existing_sp_states_preserve_other_bits(self):
        u = self.machine()
        for old in range(256):
            u.mem_write(0x612A06, bytes([old])); u.mem_write(0x5DC546, bytes([255-old]))
            u.mem_write(0x488DA0, b'\0\0\x11\x12\x13\x14\x15')
            # Start after stack-save prologue; all policy instructions execute.
            self.run_code(u, 0x319DE4, 0x319E30)
            self.assertEqual(u.mem_read(0x612A06, 1)[0], old | 3)
            self.assertEqual(u.mem_read(0x5DC546, 1)[0], (255-old) | 3)
            self.assertEqual(bytes(u.mem_read(0x488DA0, 7)), b'\1\1\x11\x12\x13\x14\x15')

    def test_sp_progress_queries_remain_independent(self):
        u = self.machine(); events = [4, 10, 15, 20, 28]
        for mask in range(32):
            u.mem_write(0x488DA0, b'\1\1' + bytes(5))
            query = {event: (mask >> i) & 1 for i, event in enumerate(events)}
            self.assertEqual(self.run_code(u, 0x319E30, 0x319E84, query), events)
            self.assertEqual(list(u.mem_read(0x488DA0, 7)), [1, 1]+list(query.values()))

    def test_information_page_returns_without_reader(self):
        u = self.machine()
        for group in range(6):
            u.mem_write(0x75ECA8, struct.pack('<I', group))
            u.mem_write(0x75EC98, struct.pack('<I', 4))
            self.run_code(u, 0x31B800, 0x31C2F8 if group == 0 else 0x31B830)
            self.assertEqual(struct.unpack('<I', u.mem_read(0x75EC98, 4))[0], 0 if group == 0 else 4)

    def test_native_rewards_and_decline(self):
        u = self.machine()
        expected = [(2000000, 2000), (2000000, 1000), (2000000, 2000),
                    (2000000, 2000), (4000000, 4000)]
        for group, (money, bs) in enumerate(expected, 1):
            for state in (8, 9):
                u.mem_write(0x5DBB20, bytes(0xC00)); u.mem_write(0x5A5080, bytes(0xB0*20))
                u.mem_write(0x488DA0, b'\1\1'+bytes(5))
                for addr, value in [(0x75ECA8, group), (0x75EC98, state), (0x61E3E8, 20)]:
                    u.mem_write(addr, struct.pack('<I', value))
                self.run_code(u, 0x31BD40, 0x31C2F8)
                value = lambda a: struct.unpack('<I', u.mem_read(a, 4))[0]
                self.assertEqual(value(0x5DBB20), money if state == 8 else 0)
                self.assertEqual(value(0x5DBB68), bs if state == 8 else 0)
                self.assertEqual([value(0x5A511C+i*0xB0) for i in range(20)], [2000 if state == 8 else 0]*20)
                for part in (16, 17):
                    self.assertEqual(u.mem_read(0x5DBCBE+part*4, 1)[0], int(state == 8))

    def test_preview_uses_actual_flags_with_short_translated_labels(self):
        u = self.machine(); stack = 0x1F00000
        u.reg_write(UC_MIPS_REG_SP, stack)
        for mask in range(128):
            u.mem_write(0x488DA0, bytes((mask >> i) & 1 for i in range(7)))
            for i in range(7):
                u.reg_write(UC_MIPS_REG_S6, i)
                u.mem_write(stack+0x100, b'\x11'*0x40)
                self.run_code(u, policy.DISPLAY_VA, 0x437900)
                enabled = (mask >> i) & 1
                self.assertEqual(u.reg_read(UC_MIPS_REG_S0), enabled)
                self.assertEqual(u.mem_read(stack+(0x11E if enabled else 0x128), 1), b'\0')


if __name__ == '__main__':
    unittest.main()
