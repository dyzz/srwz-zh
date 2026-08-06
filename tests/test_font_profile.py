import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.srwz.font import GLYPH_SIZE
from tools.srwz.font_profile import FontProfileError, load_font_profile
from tools.srwz.ui_font import UiFontError, _require_nonempty_visible_rasters


PROJECT_ROOT = Path(__file__).resolve().parents[1]
UI_PROFILE = PROJECT_ROOT / "config/fonts/ui-p0-font.json"


class FontProfileTests(unittest.TestCase):
    def test_visible_empty_raster_requires_an_explicit_fallback(self):
        empty_sha256 = hashlib.sha256(bytes(GLYPH_SIZE)).hexdigest()
        with self.assertRaisesRegex(UiFontError, "explicit global fallback"):
            _require_nonempty_visible_rasters(
                [
                    {
                        "character": "薙",
                        "raster": {"packed_glyph_sha256": empty_sha256},
                    }
                ]
            )

    def test_ui_profile_inherits_the_locked_first_five_rasterizer(self):
        profile = load_font_profile(PROJECT_ROOT, UI_PROFILE)
        base = json.loads(
            (PROJECT_ROOT / "config/fonts/first-five-font.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(profile["profile_id"], "srwz-ui-p0-unified-font-v1")
        self.assertEqual(
            profile["font_flavor"]["path"],
            base["font_flavor"],
        )
        self.assertEqual(
            profile["font_lock"],
            "config/fonts/harmonyos-sans-sc.lock.json",
        )
        self.assertEqual(profile["codec"], base["codec"])
        self.assertEqual(profile["codec"]["strategy"], "rust-maximum")
        self.assertEqual(profile["rasterizer"], base["rasterizer"])
        self.assertEqual(
            profile["document"]["scene_inventory"]["expected_unique_entry_count"],
            462,
        )

    def test_inherited_profile_rejects_base_hash_drift(self):
        document = json.loads(UI_PROFILE.read_text(encoding="utf-8"))
        modified = copy.deepcopy(document)
        modified["base_font_config"]["sha256"] = "0" * 64
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temporary:
            path = Path(temporary) / "font.json"
            path.write_text(
                json.dumps(modified, ensure_ascii=False),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(FontProfileError, "SHA-256 drift"):
                load_font_profile(PROJECT_ROOT, path)

    def test_release_profile_inherits_global_harmonyos_and_stock_ascii_glyphs(self):
        profile = load_font_profile(
            PROJECT_ROOT,
            PROJECT_ROOT / "config/fonts/zh-release-font.json",
        )
        self.assertFalse(profile["rasterizer_overrides_base"])
        self.assertFalse(profile["font_lock_overrides_base"])
        self.assertEqual(
            profile["font_lock"],
            "config/fonts/harmonyos-sans-sc.lock.json",
        )
        self.assertEqual(
            profile["rasterizer"]["cjk_fixed_canvas"],
            {
                "x_offset": 0,
                "y_offset": 1,
                "reason": (
                    "Render every CJK glyph from the global HarmonyOS Sans SC "
                    "Regular source at one 22px em and one shared baseline in "
                    "the fixed 24x24 cell. Character-specific trimming, "
                    "resizing, point sizes and corrections are forbidden."
                ),
            },
        )
        self.assertEqual(
            profile["unsupported_character_fallbacks"][0]["characters"],
            "〜∀♪",
        )
        self.assertTrue(
            profile["document"][
                "reraster_all_selected_visible_characters"
            ]
        )
        visible_ascii = profile["document"]["visible_ascii_policy"]
        self.assertEqual(
            visible_ascii["mode"], "original-fullwidth-two-byte"
        )
        self.assertTrue(visible_ascii["preserve_original_glyphs"])
        self.assertTrue(
            visible_ascii["forbid_raw_visible_ascii_alphanumerics"]
        )
        self.assertTrue(visible_ascii["preserve_raw_ascii_punctuation"])
        self.assertTrue(visible_ascii["allow_raw_space"])
        self.assertTrue(
            set("ZAFTPLANTLSWM") <= set(visible_ascii["characters"])
        )


if __name__ == "__main__":
    unittest.main()
