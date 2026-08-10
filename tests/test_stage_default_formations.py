import hashlib
import json
import unittest
from dataclasses import asdict
from pathlib import Path

from tools.srwz.stage_formations import (
    FormationCell,
    FormationGroup,
    formation_inventory_sha256,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG = PROJECT_ROOT / "config/full-story-components.json"


class StageDefaultFormationTests(unittest.TestCase):
    def test_reviewed_global_term_asset_is_locked(self):
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        reference = config["remaining_ui"]["stage_default_formations"]
        payload = (PROJECT_ROOT / reference["path"]).read_bytes()
        self.assertEqual(len(payload), reference["size"])
        self.assertEqual(hashlib.sha256(payload).hexdigest(), reference["sha256"])

        document = json.loads(payload.decode("utf-8"))
        terms = document["translations_by_source_text"]
        self.assertEqual(document["editorial_status"], "reviewed")
        self.assertTrue(
            document["policy"]["discover_all_locked_structural_occurrences"]
        )
        self.assertTrue(document["policy"]["preserve_record_metadata"])
        self.assertEqual(len(terms), 103)
        self.assertEqual(terms["エゥーゴ"], "奥古")
        self.assertEqual(terms["グローリー・スター１"], "荣耀之星1")
        self.assertEqual(terms["ザフト"], "ZAFT")
        self.assertEqual(terms["ザンベース"], "桑贝斯")

    def test_inventory_hash_locks_order_sources_and_metadata(self):
        groups = (
            FormationGroup(
                stage_index=2,
                layout="record23+6",
                slot_size=23,
                stride=29,
                cells=(
                    FormationCell(100, "ザフト", 7, "00020d03000c"),
                    FormationCell(129, "ザフト", 7, "00020d030000"),
                ),
            ),
        )
        payload = json.dumps(
            [asdict(group) for group in groups],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.assertEqual(
            formation_inventory_sha256(groups),
            hashlib.sha256(payload).hexdigest(),
        )
        changed = (
            FormationGroup(
                stage_index=2,
                layout="record23+6",
                slot_size=23,
                stride=29,
                cells=(
                    FormationCell(100, "ザフト", 7, "00020d03000c"),
                    FormationCell(129, "ザフト", 7, "00020d030004"),
                ),
            ),
        )
        self.assertNotEqual(
            formation_inventory_sha256(groups),
            formation_inventory_sha256(changed),
        )


if __name__ == "__main__":
    unittest.main()
