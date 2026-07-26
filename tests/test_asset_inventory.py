import copy
import json
import unittest
from pathlib import Path

from tools.srwz.assets import (
    AssetInventoryConfig,
    AssetInventoryError,
    changed_ranges,
    classify_stream_tail,
    compact_asset_manifest,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "assets" / "archive-inventory.json"


class AssetInventoryTests(unittest.TestCase):
    def setUp(self):
        self.config_raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    def test_repository_asset_config_is_strict_and_complete(self):
        config = AssetInventoryConfig.from_mapping(self.config_raw)

        self.assertEqual(config.schema_version, 1)
        self.assertEqual(len(config.archives), 14)
        self.assertEqual(len(config.direct_members), 3)
        self.assertEqual(
            config.archive_for_member("KURODATA/KVMDATA.BIN").storage,
            "raw",
        )
        self.assertIn("SLPS_258.87", config.required_members)

    def test_rejects_unknown_top_level_config_key(self):
        raw = copy.deepcopy(self.config_raw)
        raw["unexpected"] = True

        with self.assertRaisesRegex(AssetInventoryError, "unknown"):
            AssetInventoryConfig.from_mapping(raw)

    def test_rejects_duplicate_archive_member(self):
        raw = copy.deepcopy(self.config_raw)
        raw["archives"][1]["member"] = raw["archives"][0]["member"]

        with self.assertRaisesRegex(AssetInventoryError, "duplicates"):
            AssetInventoryConfig.from_mapping(raw)

    def test_rejects_archive_and_direct_member_overlap(self):
        raw = copy.deepcopy(self.config_raw)
        raw["direct_members"].append(raw["archives"][0]["member"])

        with self.assertRaisesRegex(AssetInventoryError, "overlap"):
            AssetInventoryConfig.from_mapping(raw)

    def test_rejects_unsafe_member_path(self):
        raw = copy.deepcopy(self.config_raw)
        raw["direct_members"][0] = "../OUTSIDE.BIN"

        with self.assertRaisesRegex(AssetInventoryError, "safe relative"):
            AssetInventoryConfig.from_mapping(raw)

    def test_rejects_unknown_storage_mode(self):
        raw = copy.deepcopy(self.config_raw)
        raw["archives"][0]["storage"] = "maybe"

        with self.assertRaisesRegex(AssetInventoryError, "unsupported storage"):
            AssetInventoryConfig.from_mapping(raw)

    def test_classifies_stream_tail_without_guessing_padding(self):
        self.assertEqual(classify_stream_tail(b"abc", 3), "complete")
        self.assertEqual(classify_stream_tail(b"abc\0\0", 3), "zero_padding")
        self.assertEqual(classify_stream_tail(b"abc\0x", 3), "nonzero_tail")

    def test_reports_half_open_changed_ranges(self):
        self.assertEqual(
            changed_ranges(b"abcdefghi", b"abXdeYZhi"),
            [(2, 3), (5, 7)],
        )

    def test_rejects_reference_size_mismatch(self):
        with self.assertRaisesRegex(AssetInventoryError, "reference size"):
            changed_ranges(b"abc", b"ab")

    def test_compact_manifest_drops_per_picture_and_chunk_details(self):
        report = {
            "schema_version": 1,
            "scope": "test",
            "source": {},
            "config_sha256": "0" * 64,
            "archive_count": 1,
            "direct_member_count": 1,
            "totals": {"tim2_record_count": 2, "picture_count": 2},
            "archives": [
                {
                    "name": "A",
                    "member": "A.BIN",
                    "storage": "raw",
                    "size": 1,
                    "sha256": "1" * 64,
                    "chunk_count": 1,
                    "decode_status_counts": {"not_compressed": 1},
                    "decoded_size": None,
                    "raw_tim2_magic_count": 1,
                    "tim2_record_count": 1,
                    "picture_count": 1,
                    "formats": [],
                    "chunks": [{"tim2_pictures": [{"width": 1}]}],
                }
            ],
            "direct_members": [
                {
                    "member": "B.BIN",
                    "size": 1,
                    "sha256": "2" * 64,
                    "raw_tim2_magic_count": 1,
                    "tim2_record_count": 1,
                    "picture_count": 1,
                    "formats": [],
                    "pictures": [{"width": 1}],
                }
            ],
            "reference_kvm_comparison": None,
        }

        compact = compact_asset_manifest(report, "2026-07-25")

        self.assertNotIn("chunks", compact["archives"][0])
        self.assertNotIn("pictures", compact["direct_members"][0])


if __name__ == "__main__":
    unittest.main()
