import copy
import json
import tempfile
import unittest
from pathlib import Path

from tools.srwz.font_profile import FontProfileError, load_font_profile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
UI_PROFILE = PROJECT_ROOT / "config/fonts/ui-p0-font.json"


class FontProfileTests(unittest.TestCase):
    def test_ui_profile_inherits_the_locked_first_five_rasterizer(self):
        profile = load_font_profile(PROJECT_ROOT, UI_PROFILE)
        base = json.loads(
            (PROJECT_ROOT / "config/fonts/first-five-font.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(profile["profile_id"], "srwz-ui-p0-unified-font-v1")
        self.assertEqual(profile["font_lock"], base["font_lock"])
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


if __name__ == "__main__":
    unittest.main()
