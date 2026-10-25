"""Height operands 81..89 lower the glyph record by one unit (native execution)."""
from pathlib import Path
import hashlib, json, struct, sys, unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from srwz.library_body_metrics import apply_library_body_metrics
from srwz.library_optical_metrics import apply_library_optical_metrics, layout

FONT = {'original': 0x46E330, 'best': 0x46EB30, 'sp': 0x4ED5B0}


def native_executable(edition):
    cfg = json.loads((ROOT / f'config/editions/{edition}/edition.json').read_text())
    iso = ROOT / cfg['source_iso']['path']
    if not iso.is_file():
        raise unittest.SkipTest('native source disc unavailable')
    from srwz.iso9660 import member_map, scan_iso9660
    member = member_map(scan_iso9660(iso))[cfg['executable']['member']]
    with iso.open('rb') as f:
        f.seek(member.extent_lba * 2048)
        data = f.read(member.size)
    assert hashlib.sha256(data).hexdigest() == cfg['executable']['sha256']
    return data


class LoweredOpticalHeightTests(unittest.TestCase):
    def test_handler_flag_height_and_record_y(self):
        try:
            from unicorn import Uc, UC_ARCH_MIPS, UC_MODE_MIPS64, UC_MODE_LITTLE_ENDIAN, UC_HOOK_CODE
            from unicorn.mips_const import (UC_CPU_MIPS64_5KEF, UC_MIPS_REG_16, UC_MIPS_REG_17, UC_MIPS_REG_20,
                                            UC_MIPS_REG_29, UC_MIPS_REG_PC)
        except ImportError:
            self.skipTest('optional Unicorn MIPS64 is unavailable')
        # operand -> (decoded height, flag byte at SP+58, record y delta)
        cases = {0x89: (9, 0xFF, 1), 0x81: (1, 0xFF, 1), 0x8A: (10, 0, 0), 0x8B: (11, 1, -1),
                 0x8E: (14, 1, -1), 0x0C: (12, 0, 0), 0x09: (9, 0, 0), 0x80: (0x80, 0, 0),
                 0x8F: (0x8F, 0, 0)}
        for edition in ('original', 'best', 'sp'):
            native = native_executable(edition)
            patched = apply_library_optical_metrics(apply_library_body_metrics(native, edition)[0], edition)[0]
            s = layout(edition)
            # The repacked control area puts the 33 handler at base+28 (table entry two).
            handler, loop, geometry, font = s['base'] + 28, s['loop'], s['geometry'], FONT[edition]
            self.assertEqual(struct.unpack_from('<I', patched, s['table'] + 4 - s['delta'])[0], handler)
            ph = struct.unpack_from('<I', patched, 28)[0]
            _, load_off, load_va, _, file_size, *_ = struct.unpack_from('<8I', patched, ph)
            for operand, (height, flag, dy) in cases.items():
                with self.subTest(edition=edition, operand=hex(operand)):
                    u = Uc(UC_ARCH_MIPS, UC_MODE_MIPS64 | UC_MODE_LITTLE_ENDIAN)
                    # The default R4000 model lacks MOVN, which the EE (R5900) has.
                    u.ctl_set_cpu_model(UC_CPU_MIPS64_5KEF)
                    u.mem_map(0, 32 << 20)
                    u.mem_map(0x70000000, 0x1000)
                    u.mem_write(load_va, patched[load_off:load_off + file_size])
                    text, stack, record = 0x1900000, 0x1FF0000, 0x1A00000
                    u.mem_write(text, bytes([operand]))
                    u.mem_write(stack + 0x58, b'\xAA' * 4)
                    u.mem_write(font + 0x48, b'\x01\x00')
                    u.reg_write(UC_MIPS_REG_20, text)
                    u.reg_write(UC_MIPS_REG_17, font)
                    u.reg_write(UC_MIPS_REG_29, stack)

                    def stop(uc, pc, size, data, at=loop):
                        if pc == at:
                            uc.emu_stop()
                    hook = u.hook_add(UC_HOOK_CODE, stop)
                    u.emu_start(handler, 0, count=40)
                    u.hook_del(hook)
                    self.assertEqual(u.reg_read(UC_MIPS_REG_PC), loop)
                    self.assertEqual(bytes(u.mem_read(stack + 0x58, 2)), bytes([flag, operand]))
                    self.assertEqual(struct.unpack('<H', bytes(u.mem_read(font + 0x16, 2)))[0], height)
                    self.assertEqual(struct.unpack('<H', bytes(u.mem_read(0x70000036, 2)))[0], height)
                    self.assertEqual(bytes(u.mem_read(font + 0x48, 2)), b'\0\0')
                    # Glyph record word: x in the low half, y in the high half.
                    u.mem_write(0x70000030, struct.pack('<hh', 100, 40))
                    u.reg_write(UC_MIPS_REG_16, record)
                    u.emu_start(geometry, 0, count=6)
                    self.assertEqual(struct.unpack('<hh', bytes(u.mem_read(record + 4, 4))), (100, 40 + dy))


if __name__ == '__main__':
    unittest.main()
