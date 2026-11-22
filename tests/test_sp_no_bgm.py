"""Install the Viewer patch on a native SP ELF and inspect its actual MIPS hooks."""
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from special_disc.no_bgm.apply import apply_no_bgm
from srwz.iso9660 import member_map, scan_iso9660
from srwz.proportional_payload import LAYOUTS


class ViewerMuteTests(unittest.TestCase):
    def test_native_audio_entries_and_payload_layout(self):
        iso = next((ROOT / 'build/iso/sources').glob('*Special Disc*.iso'), None)
        if iso is None or not shutil.which('mipsel-linux-gnu-as'):
            self.skipTest('SP source ISO and R5900 assembler required')
        member = member_map(scan_iso9660(iso))['SLPS_259.20']
        with iso.open('rb') as disc:
            disc.seek(member.extent_lba * 2048)
            native = bytearray(disc.read(member.size))
        ph = struct.unpack_from('<I', native, 28)[0]
        count = struct.unpack_from('<H', native, 44)[0]
        segments = list(struct.iter_unpack('<8I', native[ph:ph + count * 32]))

        def offset(address):
            for kind, start, base, _, size, *_ in segments:
                if kind == 1 and base <= address < base + size:
                    return start + address - base
            self.fail(f'address outside native ELF: {address:#x}')

        # In a full build the event gallery already moved this heap boundary.
        struct.pack_into('<I', native, offset(0x44e734), 0x8c0000)
        with tempfile.TemporaryDirectory() as work:
            result, report = apply_no_bgm(bytes(native), workdir=Path(work))
        for address in (0x182e30, 0x182fc0, 0x18c8a0):
            start = offset(address)
            self.assertEqual(result[start:start + 8], native[start:start + 8])
        symbols = report['symbols']
        self.assertGreater(symbols['NO_BGM'], 0x7d)
        for address, handler in [(0x411478, 'resolve'), (0x40f848, 'restore_song'),
                                 (0x1439e4, 'return_music'), (0x18b740, 'volume'),
                                 (0x18bcf4, 'volume'), (0x18be24, 'volume'),
                                 (0x18beb0, 'volume'), (0x18bf3c, 'volume')]:
            self.assertEqual(struct.unpack_from('<I', result, offset(address))[0],
                             0x0c000000 | (symbols[handler] >> 2))
        base = int(report['payload_address'], 16)
        fonts = LAYOUTS['sp']
        self.assertGreaterEqual(base, fonts['base'] + fonts['capacity'])
        self.assertLessEqual(base + report['payload_bytes'], 0x820000)
