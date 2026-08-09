import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config/release/v0.1.0.json"
TOOL_PATH = PROJECT_ROOT / "tools/build_release.py"

SPEC = importlib.util.spec_from_file_location("build_release", TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
BUILD_RELEASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD_RELEASE)


class ReleasePatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cls.iso_config = json.loads(
            (
                PROJECT_ROOT
                / "config/iso/zh-release-full-story-build.json"
            ).read_text(encoding="utf-8")
        )

    def test_release_name_and_iso_binding(self):
        self.assertEqual(self.config["version"], "0.1.0")
        self.assertEqual(self.config["tag"], "v0.1.0")
        self.assertEqual(
            self.config["target_iso"]["path"],
            self.iso_config["output"]["path"],
        )
        self.assertEqual(
            self.config["target_iso"]["sha256"],
            self.iso_config["output"]["expected_sha256"],
        )
        self.assertEqual(
            Path(self.config["target_iso"]["path"]).name,
            "srwz-zh-v0.1.0.iso",
        )

    def test_release_output_is_patch_only(self):
        output_dir = PROJECT_ROOT / self.config["output"]["directory"]
        if not output_dir.exists():
            self.skipTest("release package has not been built locally")
        self.assertEqual(list(output_dir.glob("*.iso")), [])
        self.assertTrue(
            (output_dir / self.config["xdelta"]["patch_filename"]).is_file()
        )
        archive = output_dir / self.config["output"]["archive_filename"]
        with zipfile.ZipFile(archive) as package:
            names = package.namelist()
        self.assertFalse(any(name.lower().endswith(".iso") for name in names))

    def test_deterministic_zip_metadata_and_member_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            second = root / "b.txt"
            first = root / "a.txt"
            second.write_text("B\n", encoding="utf-8")
            first.write_text("A\n", encoding="utf-8")
            left = root / "left.zip"
            right = root / "right.zip"
            BUILD_RELEASE.write_deterministic_zip(left, [second, first])
            BUILD_RELEASE.write_deterministic_zip(right, [first, second])
            self.assertEqual(left.read_bytes(), right.read_bytes())
            with zipfile.ZipFile(left) as archive:
                self.assertEqual(archive.namelist(), ["a.txt", "b.txt"])
                self.assertTrue(
                    all(
                        item.date_time == BUILD_RELEASE.ZIP_TIMESTAMP
                        for item in archive.infolist()
                    )
                )


if __name__ == "__main__":
    unittest.main()
