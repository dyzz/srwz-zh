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
CONFIG_PATH = PROJECT_ROOT / "config/assets/ui-info-atlas-zh.json"
MANIFEST_PATH = PROJECT_ROOT / "manifests/ui-info-atlas-zh-validation.json"
RUNTIME_MANIFEST_PATH = (
    PROJECT_ROOT / "manifests/ui-info-atlas-zh-runtime-validation.json"
)
ISO_CONFIG_PATH = PROJECT_ROOT / "config/iso/ui-info-atlas-zh-build.json"
COMPONENT_PATH = (
    PROJECT_ROOT
    / "work/build/ui-info-atlas-zh/components/KURODATA/KVMDATA.BIN"
)


class UiAtlasLocalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        cls.runtime_manifest = json.loads(
            RUNTIME_MANIFEST_PATH.read_text(encoding="utf-8")
        )
        cls.iso_config = json.loads(
            ISO_CONFIG_PATH.read_text(encoding="utf-8")
        )

    def test_text_mask_is_bounded_and_requires_erased_preimage(self):
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
        payloads, report = build_ui_atlas_localization(
            PROJECT_ROOT,
            WORK_ROOT,
            CONFIG_PATH,
        )
        self.assertEqual(report, self.manifest)
        self.assertEqual(payloads["archive"], COMPONENT_PATH.read_bytes())
        self.assertEqual(
            hashlib.sha256(payloads["archive"]).hexdigest(),
            "04c7b44d99676ada6cd19dccf3ef3d250b9f440902f854857a59645245aad933",
        )

    def test_render_and_runtime_boundaries_are_explicit(self):
        self.assertEqual(
            self.manifest["status"],
            "static_localized_component_validated_runtime_mapping_pending",
        )
        self.assertEqual(
            self.manifest["localized_label"]["character_count"],
            2,
        )
        self.assertEqual(
            self.manifest["text_audit"]["added_pixel_count"],
            318,
        )
        self.assertEqual(
            self.manifest["target"]["mask_audit"]["changed_pixel_count"],
            421,
        )
        self.assertEqual(self.manifest["runtime"]["status"], "not_tested")
        self.assertTrue(all(self.manifest["acceptance"].values()))

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

        visit(self.manifest)

    def test_iso_is_exact_and_runtime_mapping_remains_pending(self):
        self.assertEqual(
            self.runtime_manifest["status"],
            "static_localization_iso_validated_runtime_mapping_pending",
        )
        self.assertEqual(
            self.runtime_manifest["iso_build"]["output"]["sha256"],
            "d31f3d3dbffc59da595b2d27bb516efec34af12426bda2b3d6f2a67ffdb9ddd0",
        )
        self.assertEqual(
            self.runtime_manifest["runtime"]["expected_texture_delta"][
                "changed_pixel_count"
            ],
            421,
        )
        self.assertEqual(
            self.runtime_manifest["iso_build"]["unchanged_member_count"],
            65,
        )
        self.assertEqual(self.runtime_manifest["runtime"]["status"], "not_tested")
        self.assertEqual(
            self.iso_config["replacements"][0]["sha256"],
            self.manifest["outputs"]["archive"]["sha256"],
        )


if __name__ == "__main__":
    unittest.main()
