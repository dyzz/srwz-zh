import copy
import json
import unittest
from pathlib import Path

from tools.srwz.assets import (
    AssetInventoryConfig,
    AssetInventoryError,
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

if __name__ == "__main__":
    unittest.main()
