import copy
import json
import unittest
from pathlib import Path

from tools.srwz.font_flavor import load_font_flavor_reference
from tools.srwz.font_source import (
    FontSourceError,
    validate_font_lock,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FontSourceTests(unittest.TestCase):
    def test_no_scene_config_bypasses_the_global_font_flavor(self):
        violations = []
        allowed_flavors = {
            "config/fonts/zh-localization-font.json",
            "config/fonts/zh-localization-font-light.json",
        }

        def visit(value, path):
            if isinstance(value, dict):
                for key, child in value.items():
                    child_path = f"{path}.{key}"
                    if key in {"font_lock", "font_lock_sha256"}:
                        violations.append(child_path)
                    if key == "font_flavor" and child not in allowed_flavors:
                        violations.append(child_path)
                    visit(child, child_path)
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    visit(child, f"{path}[{index}]")

        for path in sorted((PROJECT_ROOT / "config").rglob("*.json")):
            if path.parent == PROJECT_ROOT / "config/fonts" and (
                path.name.endswith(".lock.json")
                or path.name.startswith("zh-localization-font")
            ):
                continue
            visit(
                json.loads(path.read_text(encoding="utf-8")),
                str(path.relative_to(PROJECT_ROOT)),
            )
        self.assertEqual(violations, [])

    def test_intermission_atlas_uses_the_locked_harmonyos_light_flavor(self):
        config = json.loads(
            (
                PROJECT_ROOT
                / "config/assets/ui-intermission-atlas-zh.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            config["localized_label"]["font_flavor"],
            "config/fonts/zh-localization-font-light.json",
        )
        flavor = load_font_flavor_reference(
            PROJECT_ROOT,
            config["localized_label"]["font_flavor"],
        )
        lock = json.loads(
            (PROJECT_ROOT / flavor["font_lock"]).read_text(encoding="utf-8")
        )
        validate_font_lock(lock)
        self.assertEqual(lock["family"], "HarmonyOS Sans SC")
        self.assertEqual(lock["style"], "Light")
        self.assertEqual(
            lock["font"]["sha256"],
            "dd366290b40861bc6ced85801e850ab66d6fe4c5b33bc43095a9747fa29288d8",
        )

    def test_all_chinese_assets_resolve_the_harmonyos_flavor(self):
        config = json.loads(
            (
                PROJECT_ROOT / "config/fonts/zh-font-base.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            config["font_flavor"],
            "config/fonts/zh-localization-font.json",
        )
        flavor = load_font_flavor_reference(
            PROJECT_ROOT,
            config["font_flavor"],
        )
        lock = json.loads(
            (PROJECT_ROOT / flavor["font_lock"]).read_text(encoding="utf-8")
        )
        validate_font_lock(lock)
        self.assertEqual(lock["family"], "HarmonyOS Sans SC")
        self.assertEqual(lock["version"], "1.0")
        self.assertEqual(
            lock["license"]["spdx"],
            "LicenseRef-HarmonyOS-Sans-Fonts-License",
        )
        self.assertTrue(lock["license"]["notice_required"])
        self.assertEqual(
            flavor["unsupported_character_fallbacks"][0]["characters"],
            "〜∀♪",
        )

    def test_font_lock_rejects_an_unapproved_download_host(self):
        lock = json.loads(
            (PROJECT_ROOT / "config/fonts/harmonyos-sans-sc.lock.json").read_text(
                encoding="utf-8"
            )
        )
        modified = copy.deepcopy(lock)
        modified["archive"]["url"] = "https://example.com/font.zip"
        with self.assertRaisesRegex(FontSourceError, "allowed source"):
            validate_font_lock(modified)
