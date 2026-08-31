from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools.srwz.aid_battle_prompts import build_aid_battle_prompts


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG = PROJECT_ROOT / "config/assets/aid-battle-prompts-zh.json"


class AidBattlePromptsTest(unittest.TestCase):
    def test_locked_component_rebuilds_with_index_and_alpha_guards(self) -> None:
        payload, reference, localized, report = build_aid_battle_prompts(
            PROJECT_ROOT,
            CONFIG,
        )
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(len(payload), config["source"]["size"])
        self.assertEqual(len(reference), 512 * 1024 * 4)
        self.assertEqual(len(localized), 512 * 1024 * 4)
        self.assertTrue(all(report["acceptance"].values()))
        self.assertTrue(report["atlas"]["clut_preserved_byte_exact"])
        self.assertTrue(report["atlas"]["background_transparent_in_all_palette_banks"])
        self.assertTrue(report["atlas"]["non_target_logical_indexes_preserved_byte_exact"])
        self.assertTrue(report["animation_stream"]["preserved_byte_exact"])
        translations = {
            item["entry_id"]: item["translation"]
            for item in report["atlas"]["labels"]
        }
        self.assertEqual(translations["aid/tri-attack"], "TRI攻击")
        self.assertEqual(translations["aid/counter"], "先手反击")


if __name__ == "__main__":
    unittest.main()
