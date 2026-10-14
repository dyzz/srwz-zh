"""Protect production metadata and executable preimages during native caption builds."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import struct
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "main_event_subtitle_build", ROOT / "tools/event_subtitles/build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def catalog_row(name, lba, count):
    return name.encode("ascii").ljust(40, b"\0") + struct.pack("<II", lba, count)


class NativeCaptionProtectionTests(unittest.TestCase):
    def test_inherited_non_target_catalog_difference_is_preserved(self):
        before = {
            "EFF/VEFF2DX.BIN": SimpleNamespace(extent_lba=100, size=4096),
            "COMPDATA.BIN": SimpleNamespace(extent_lba=200, size=2048),
        }
        data = (catalog_row("EFF/VEFF2DX.BIN", 100, 2)
                + catalog_row("COMPDATA.BIN", 199, 1) + bytes(48))
        updated, receipt = build.patch_catalog(
            data, before, {"EFF/VEFF2DX.BIN": (300, 4097)})
        self.assertEqual(updated[48:], data[48:])
        self.assertEqual(struct.unpack_from("<II", updated, 40), (300, 3))
        self.assertEqual(receipt["inherited_non_target_catalog_differences"][0]
                         ["member"], "COMPDATA.BIN")

    def test_target_catalog_difference_rejects_without_repairing_it(self):
        before = {"EFF/VEFF2DX.BIN": SimpleNamespace(extent_lba=100, size=2048)}
        with self.assertRaisesRegex(ValueError, "preimage mismatch"):
            build.patch_catalog(catalog_row("EFF/VEFF2DX.BIN", 99, 1),
                                before, {"EFF/VEFF2DX.BIN": (300, 2048)})

    def test_wrong_executable_preimage_does_not_mutate_bytes(self):
        elf = bytearray(b"\0" * 16)
        with self.assertRaisesRegex(ValueError, "Instruction preimage mismatch"):
            build.patch(elf, 0xfe584, b"abcd", b"efgh")
        self.assertEqual(elf, bytes(16))

    def test_unknown_udf_profile_rejected_before_opening_image(self):
        with self.assertRaisesRegex(ValueError, "unknown subtitle relocation profile"):
            build.relocate("/does/not/exist.iso", {"STAGE.BIN": (300, 2048)},
                           allowed_members={"STAGE.BIN"})


if __name__ == "__main__":
    unittest.main()
