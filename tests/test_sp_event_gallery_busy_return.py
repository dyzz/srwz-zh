"""Execute the gallery's deferred-entry ABI; this is not PS2 graphics proof."""
import shutil
import struct
import sys
import tempfile
import unittest
from pathlib import Path

try:
    from unicorn import Uc, UC_ARCH_MIPS, UC_MODE_MIPS64, UC_MODE_LITTLE_ENDIAN
    from unicorn.mips_const import (
        UC_MIPS_REG_A0, UC_MIPS_REG_V0, UC_MIPS_REG_RA, UC_MIPS_REG_PC,
        UC_MIPS_REG_SP, UC_MIPS_REG_S0, UC_MIPS_REG_S1,
        UC_MIPS_REG_S2, UC_MIPS_REG_S3,
    )
except ImportError:
    raise unittest.SkipTest("optional Unicorn MIPS64 runtime not installed")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from special_disc.event_gallery.apply import assemble_runtime, RUNTIME_BASE, encode_talk, PROPOSAL, load_config


class DeferredGalleryEntryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not all(shutil.which(f"mipsel-linux-gnu-{tool}") for tool in ("as", "ld", "objcopy")):
            raise unittest.SkipTest("MIPS binutils not installed")
        config = load_config()
        with tempfile.TemporaryDirectory() as directory:
            cls.runtime, _ = assemble_runtime(Path(directory), config["entries"], {}, encode_talk(config["talk"], PROPOSAL))

    def test_busy_entry_returns_unmodified_packet_cursor_and_preserves_request(self):
        # Native 143ea8 enters with V0 holding its dispatch address. Returning
        # that stale value causes the caller to overwrite code with GIF data.
        for sound in (1, 2, 4, 5, 7):
            for cursor, stale in ((0x30519950, 0x143EA0), (0x30519B30, 0xDEADBEEF)):
                with self.subTest(sound=sound, cursor=hex(cursor)):
                    vm = Uc(UC_ARCH_MIPS, UC_MODE_MIPS64 | UC_MODE_LITTLE_ENDIAN)
                    vm.mem_map(0, 32 << 20)
                    vm.mem_write(RUNTIME_BASE, self.runtime)
                    vm.mem_write(0x821F00, struct.pack("<2I", 0, 1))
                    vm.mem_write(0x620890, struct.pack("<I", sound))
                    vm.reg_write(UC_MIPS_REG_A0, cursor)
                    vm.reg_write(UC_MIPS_REG_V0, stale)
                    vm.reg_write(UC_MIPS_REG_RA, 0x143EB0)
                    vm.reg_write(UC_MIPS_REG_SP, 0x1FFF000)
                    saved = (UC_MIPS_REG_S0, UC_MIPS_REG_S1, UC_MIPS_REG_S2, UC_MIPS_REG_S3)
                    for index, register in enumerate(saved):
                        vm.reg_write(register, 0x123400 + index)
                    vm.emu_start(RUNTIME_BASE + 0x100, 0x143EB0, count=100)
                    self.assertEqual(vm.reg_read(UC_MIPS_REG_PC), 0x143EB0)
                    self.assertEqual(vm.reg_read(UC_MIPS_REG_V0), cursor)
                    self.assertEqual(vm.reg_read(UC_MIPS_REG_SP), 0x1FFF000)
                    self.assertEqual(bytes(vm.mem_read(0x821F00, 8)), struct.pack("<2I", 0, 1))
                    self.assertEqual(bytes(vm.mem_read(0x620890, 4)), struct.pack("<I", sound))
                    for index, register in enumerate(saved):
                        self.assertEqual(vm.reg_read(register), 0x123400 + index)
