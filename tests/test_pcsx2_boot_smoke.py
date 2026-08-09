import tempfile
import unittest
from pathlib import Path

from tools.srwz.pcsx2_boot_smoke import (
    analyze_boot_log,
    build_boot_smoke_report,
)


class Pcsx2BootSmokeTests(unittest.TestCase):
    def test_clean_log_proves_dvd_and_elf_without_tlb(self):
        report = analyze_boot_log(
            "Image type  = DVD\n"
            "ELF (cdrom0:\\\\SLPS_258.87;1) Game CRC = 0xA624CDFC "
            "is executing.\n"
        )
        self.assertTrue(report["dvd_recognized"])
        self.assertTrue(report["elf_executing"])
        self.assertTrue(report["no_tlb_miss"])
        self.assertEqual(report["tlb_miss_count"], 0)
        self.assertIsNone(report["first_tlb_miss"])
        self.assertTrue(report["no_illegal_instruction"])
        self.assertEqual(report["illegal_instruction_count"], 0)
        self.assertTrue(report["no_trap"])
        self.assertEqual(report["trap_count"], 0)

    def test_tlb_log_is_fail_closed(self):
        report = analyze_boot_log(
            "Image type  = DVD\n"
            "ELF (cdrom0:\\\\SLPS_258.87;1) is executing.\n"
            "TLB Miss, pc=0x1c6ea0 addr=0x2000000 [store]\n"
        )
        self.assertFalse(report["no_tlb_miss"])
        self.assertEqual(report["tlb_miss_count"], 1)
        self.assertIn("0x1c6ea0", report["first_tlb_miss"])

    def test_illegal_instruction_and_trap_are_fail_closed(self):
        report = analyze_boot_log(
            "Image type  = DVD\n"
            "ELF (cdrom0:\\\\SLPS_258.87;1) is executing.\n"
            "Illegal Instruction at pc=0x00756e50\n"
            "Execution trapped: pc=0x00789d0c\n"
        )
        self.assertFalse(report["no_illegal_instruction"])
        self.assertEqual(report["illegal_instruction_count"], 1)
        self.assertFalse(report["no_trap"])
        self.assertEqual(report["trap_count"], 1)

    def test_report_keeps_static_and_runtime_boundaries(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            iso = root / "build/iso/test/test.iso"
            pcsx2 = root / "work/runtime/PCSX2"
            log = root / "work/runtime/test/emulog.txt"
            host = root / "work/runtime/test/host-output.txt"
            for path, content in (
                (iso, b"iso"),
                (pcsx2, b"pcsx2"),
                (
                    log,
                    (
                        b"Image type  = DVD\n"
                        b"ELF (cdrom0:\\\\SLPS_258.87;1) is executing.\n"
                    ),
                ),
                (host, b""),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            report = build_boot_smoke_report(
                project_root=root,
                iso_path=iso,
                pcsx2_path=pcsx2,
                log_path=log,
                host_output_path=host,
                argv=["PCSX2", "test.iso"],
                pine_version="PCSX2 v2.6.3",
                game_title="Super Robot Taisen Z",
                game_id="SLPS-25887",
                pine_status=0,
                duration_seconds=6.0,
                process_exit_code=0,
            )
        self.assertEqual(report["status"], "passed")
        self.assertTrue(all(report["checks"].values()))
        self.assertIn("no_illegal_instruction", report["checks"])
        self.assertIn("no_trap", report["checks"])
        self.assertIn("does not prove navigation", report["boundary"])


if __name__ == "__main__":
    unittest.main()
