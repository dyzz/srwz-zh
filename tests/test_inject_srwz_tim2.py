import unittest
from pathlib import Path

from tools.inject_srwz_tim2 import (
    Tim2InjectionCliError,
    require_manifest_path,
    require_work_path,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Tim2InjectionCliTests(unittest.TestCase):
    def test_accepts_archive_output_under_work(self):
        path = PROJECT_ROOT / "work" / "assets" / "writeback" / "KVM.bin"

        self.assertEqual(
            require_work_path(path, "archive output", ".bin"),
            path.resolve(),
        )

    def test_rejects_archive_output_outside_work(self):
        path = PROJECT_ROOT / "build" / "KVM.bin"

        with self.assertRaisesRegex(Tim2InjectionCliError, "must stay under"):
            require_work_path(path, "archive output", ".bin")

    def test_rejects_wrong_archive_suffix(self):
        path = PROJECT_ROOT / "work" / "assets" / "writeback" / "KVM.iso"

        with self.assertRaisesRegex(Tim2InjectionCliError, "must have a .bin"):
            require_work_path(path, "archive output", ".bin")

    def test_accepts_manifest_output_under_manifests(self):
        path = PROJECT_ROOT / "manifests" / "tim2-test.json"

        self.assertEqual(require_manifest_path(path), path.resolve())

    def test_rejects_manifest_output_outside_manifests(self):
        path = PROJECT_ROOT / "work" / "tim2-test.json"

        with self.assertRaisesRegex(Tim2InjectionCliError, "must stay under"):
            require_manifest_path(path)


if __name__ == "__main__":
    unittest.main()
