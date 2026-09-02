from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.build_aid_battle_prompts import (
    build_frozen_aid_battle_prompts,
    main as build_main,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG = PROJECT_ROOT / "config/assets/aid-battle-prompts-zh.json"


class AidBattlePromptsTest(unittest.TestCase):
    def test_locked_component_rebuilds_with_index_and_alpha_guards(self) -> None:
        with patch(
            "tools.srwz.aid_battle_prompts.build_aid_battle_prompts",
            side_effect=AssertionError("normal builds must not rasterize AID text"),
        ):
            payload, reference, localized, report = build_frozen_aid_battle_prompts(
                PROJECT_ROOT,
                CONFIG,
            )
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(config["render_policy"]["production_source"], "frozen_snapshot")
        self.assertFalse(config["render_policy"]["normal_build_rasterization"])
        self.assertEqual(len(payload), config["source"]["size"])
        self.assertEqual(len(reference), 512 * 1024 * 4)
        self.assertEqual(len(localized), 512 * 1024 * 4)
        self.assertTrue(all(report["acceptance"].values()))
        self.assertTrue(report["atlas"]["clut_preserved_byte_exact"])
        self.assertTrue(report["atlas"]["background_transparent_in_all_palette_banks"])
        self.assertTrue(report["atlas"]["non_target_logical_indexes_preserved_byte_exact"])
        self.assertTrue(report["animation_stream"]["preserved_byte_exact"])
        self.assertEqual(report["build_mode"], "locked_indexed_snapshot")
        self.assertTrue(report["render"]["frozen_render_snapshot_consumed"])
        self.assertFalse(report["render"]["normal_build_rasterization"])
        self.assertNotIn("font_file", report["inputs"])
        self.assertNotIn("font_flavor", report["inputs"])
        self.assertIn("frozen_snapshot", report["inputs"])
        translations = {
            item["entry_id"]: item["translation"]
            for item in report["atlas"]["labels"]
        }
        self.assertEqual(translations["aid/tri-attack"], "TRI攻击")
        self.assertEqual(translations["aid/counter"], "先手反击")

    def test_default_cli_does_not_render_or_rewrite_preview_pngs(self) -> None:
        with patch("sys.argv", ["build_aid_battle_prompts.py", "--force"]):
            with patch(
                "tools.srwz.imagemagick.require_imagemagick",
                side_effect=AssertionError("frozen builds must not require ImageMagick"),
            ) as require_imagemagick:
                with patch(
                    "tools.srwz.imagemagick.write_deterministic_rgba8_png",
                    side_effect=AssertionError("frozen builds must not rewrite previews"),
                ) as write_png:
                    self.assertEqual(build_main(), 0)
        require_imagemagick.assert_not_called()
        write_png.assert_not_called()


if __name__ == "__main__":
    unittest.main()
