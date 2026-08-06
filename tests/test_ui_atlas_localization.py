import hashlib
import json
import unittest
from pathlib import Path

from tools.srwz.ui_atlas_canary import AtlasMask
from tools.srwz.ui_atlas_localization import (
    UiAtlasLocalizationError,
    apply_text_mask,
    build_ui_atlas_localization,
    rgba_delta,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
PROFILES = {
    "info": {
        "stem": "ui-info-atlas-zh",
        "archive_sha256": (
            "c2e17e91730ec39e2d2deee6b29fb1607b1f6c13f75cbf0b314dd0f1a8494201"
        ),
        "iso_sha256": (
            "d31f3d3dbffc59da595b2d27bb516efec34af12426bda2b3d6f2a67ffdb9ddd0"
        ),
        "character_count": 2,
        "added_pixel_count": 330,
        "changed_pixel_count": 425,
    },
    "battle-command": {
        "stem": "ui-battle-command-atlas-zh",
        "archive_sha256": (
            "f6db010cb6c7f6adc27c7f48d8eaa1c6ebbbe499ca0a43dbcac68a4d25fe62b9"
        ),
        "iso_sha256": (
            "3e9ed4b155867cefc6b03775a20ab1ca58f7bc4c29ef7bcdfa6feceb14182dda"
        ),
        "character_count": 4,
        "added_pixel_count": 610,
        "changed_pixel_count": 2284,
    },
    "bazaar": {
        "stem": "ui-bazaar-atlas-zh",
        "archive_sha256": (
            "977f434fa01781e244cb0726875fe4823d72c24b126da5808956d1ad4a2f90af"
        ),
        "iso_sha256": (
            "9fcf33ba40c717497d6750e303db44e3a48bf814f43f4dbdebef3639912bf363"
        ),
        "character_count": 3,
        "added_pixel_count": 2844,
        "changed_pixel_count": 3713,
    },
    "intermission": {
        "stem": "ui-intermission-atlas-zh",
        "archive_sha256": (
            "880dacedd976c689d01a8b6f50e6f494c105c2f44d24d4d9fac8ff751762a77a"
        ),
        "iso_sha256": (
            "27a7563c517c155cb9fc44e2b80a06be41d1a1fb294c0f633537b19c4f9e9de2"
        ),
        "character_count": 4,
        "added_pixel_count": 1683,
        "changed_pixel_count": 2111,
    },
    "formation": {
        "stem": "ui-formation-atlas-zh",
        "archive_sha256": (
            "78f6963495d5a73f5cd23ba1557e79428aa0e04444b42de097ee51fcd8130a31"
        ),
        "iso_sha256": (
            "cc8cd7cf82583cb5ea8d52ccac6aabafa730a653ff70613ac2a07da1f763a293"
        ),
        "character_count": 4,
        "added_pixel_count": 769,
        "changed_pixel_count": 1257,
    },
}


class UiAtlasLocalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profiles = {}
        for name, expected in PROFILES.items():
            stem = expected["stem"]
            config_path = PROJECT_ROOT / f"config/assets/{stem}.json"
            manifest_path = PROJECT_ROOT / f"manifests/{stem}-validation.json"
            runtime_manifest_path = (
                PROJECT_ROOT / f"manifests/{stem}-runtime-validation.json"
            )
            iso_config_path = PROJECT_ROOT / f"config/iso/{stem}-build.json"
            cls.profiles[name] = {
                **expected,
                "config_path": config_path,
                "config": json.loads(config_path.read_text(encoding="utf-8")),
                "manifest": json.loads(
                    manifest_path.read_text(encoding="utf-8")
                ),
                "runtime_manifest": json.loads(
                    runtime_manifest_path.read_text(encoding="utf-8")
                ),
                "iso_config": json.loads(
                    iso_config_path.read_text(encoding="utf-8")
                ),
            }

    def test_text_mask_is_bounded_and_requires_mapping_preimage(self):
        erased = bytes(256 * 256 * 4)
        mask = AtlasMask.from_mapping(
            {
                "x": 4,
                "y": 5,
                "width": 2,
                "height": 2,
                "replacement_rgba": "00000000",
                "preserve_rgba": ["00000000"],
            }
        )
        output, audit = apply_text_mask(
            erased,
            bytes((0, 64, 128, 255)),
            mask,
            (bytes.fromhex("101010ff"), bytes.fromhex("808080ff")),
        )
        self.assertEqual(audit["added_pixel_count"], 3)
        self.assertTrue(audit["outside_mask_rgba_exact"])
        self.assertEqual(
            rgba_delta(erased, output, mask)["changed_pixel_count"],
            3,
        )

        invalid = bytearray(erased)
        start = (5 * 256 + 4) * 4
        invalid[start : start + 4] = bytes.fromhex("101010ff")
        with self.assertRaisesRegex(
            UiAtlasLocalizationError,
            "not erased",
        ):
            apply_text_mask(
                bytes(invalid),
                bytes((1, 0, 0, 0)),
                mask,
                (bytes.fromhex("101010ff"), bytes.fromhex("808080ff")),
            )

        mixed_background_mask = AtlasMask.from_mapping(
            {
                "x": 4,
                "y": 5,
                "width": 2,
                "height": 2,
                "replacement_rgba": "000000ff",
                "preserve_rgba": ["000000ff", "00000000"],
            }
        )
        output, audit = apply_text_mask(
            erased,
            bytes((0, 64, 128, 255)),
            mixed_background_mask,
            (bytes.fromhex("101010ff"), bytes.fromhex("808080ff")),
        )
        self.assertEqual(audit["added_pixel_count"], 3)
        self.assertTrue(audit["erased_background_preimage_exact"])
        self.assertEqual(
            rgba_delta(
                erased,
                output,
                mixed_background_mask,
            )["changed_pixel_count"],
            3,
        )

    def test_rgba_delta_rejects_pixels_outside_the_mask(self):
        before = bytes(256 * 256 * 4)
        after = bytearray(before)
        start = (20 * 256 + 20) * 4
        after[start : start + 4] = bytes.fromhex("101010ff")
        mask = AtlasMask.from_mapping(
            {
                "x": 0,
                "y": 0,
                "width": 8,
                "height": 8,
                "replacement_rgba": "00000000",
                "preserve_rgba": ["00000000"],
            }
        )
        with self.assertRaisesRegex(
            UiAtlasLocalizationError,
            "escaped",
        ):
            rgba_delta(before, bytes(after), mask)

    def test_component_and_manifest_rebuild_exactly(self):
        for name, profile in self.profiles.items():
            with self.subTest(profile=name):
                payloads, report = build_ui_atlas_localization(
                    PROJECT_ROOT,
                    WORK_ROOT,
                    profile["config_path"],
                )
                component_path = (
                    PROJECT_ROOT
                    / profile["config"]["outputs"]["component_root"]
                    / profile["config"]["target"]["member"]
                )
                self.assertEqual(report, profile["manifest"])
                self.assertEqual(payloads["archive"], component_path.read_bytes())
                self.assertEqual(
                    hashlib.sha256(payloads["archive"]).hexdigest(),
                    profile["archive_sha256"],
                )

    def test_render_and_runtime_boundaries_are_explicit(self):
        for name, profile in self.profiles.items():
            manifest = profile["manifest"]
            with self.subTest(profile=name):
                self.assertEqual(
                    manifest["status"],
                    "static_localized_component_validated_runtime_mapping_pending",
                )
                self.assertEqual(
                    manifest["localized_label"]["character_count"],
                    profile["character_count"],
                )
                self.assertEqual(
                    manifest["text_audit"]["added_pixel_count"],
                    profile["added_pixel_count"],
                )
                self.assertEqual(
                    manifest["target"]["mask_audit"]["changed_pixel_count"],
                    profile["changed_pixel_count"],
                )
                self.assertEqual(manifest["runtime"]["status"], "not_tested")
                self.assertTrue(all(manifest["acceptance"].values()))

    def test_committed_manifest_contains_no_translation_payload(self):
        def visit(value):
            if isinstance(value, dict):
                self.assertNotIn("source_text", value)
                self.assertNotIn("translation", value)
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        for name, profile in self.profiles.items():
            with self.subTest(profile=name):
                visit(profile["manifest"])

    def test_iso_is_exact_and_runtime_mapping_remains_pending(self):
        for name, profile in self.profiles.items():
            runtime_manifest = profile["runtime_manifest"]
            manifest = profile["manifest"]
            iso_config = profile["iso_config"]
            with self.subTest(profile=name):
                self.assertEqual(
                    runtime_manifest["status"],
                    "static_localization_iso_validated_runtime_mapping_pending",
                )
                self.assertEqual(
                    runtime_manifest["iso_build"]["output"]["sha256"],
                    profile["iso_sha256"],
                )
                self.assertNotEqual(
                    runtime_manifest["runtime"]["expected_texture_delta"][
                        "changed_pixel_count"
                    ],
                    profile["changed_pixel_count"],
                )
                self.assertEqual(
                    runtime_manifest["iso_build"]["unchanged_member_count"],
                    65,
                )
                self.assertEqual(
                    runtime_manifest["runtime"]["status"],
                    "not_tested",
                )
                self.assertNotEqual(
                    iso_config["replacements"][0]["sha256"],
                    manifest["outputs"]["archive"]["sha256"],
                )


if __name__ == "__main__":
    unittest.main()
