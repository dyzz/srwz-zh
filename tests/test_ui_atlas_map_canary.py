import hashlib
import json
import unittest
from pathlib import Path

from tools.srwz.iso_config import load_config
from tools.srwz.ui_atlas_canary import (
    AtlasMask,
    UiAtlasCanaryError,
    apply_masked_rgba,
    verify_masked_rgba,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = (
    PROJECT_ROOT / "config/canary/tim2-kvm2-info-map.json"
)
MANIFEST_PATH = (
    PROJECT_ROOT / "manifests/ui-info-atlas-map-canary-validation.json"
)
ISO_CONFIG_PATH = (
    PROJECT_ROOT
    / "config/iso/ui-info-atlas-map-canary-build.json"
)
RUNTIME_MANIFEST_PATH = (
    PROJECT_ROOT
    / "manifests/ui-info-atlas-map-canary-runtime-validation.json"
)
COMPONENT_ROOT = (
    PROJECT_ROOT
    / "work/build/ui-info-atlas-map-canary/components"
)
INTERMISSION_CONFIG_PATH = (
    PROJECT_ROOT
    / "config/canary/tim2-kvm6-intermission-map.json"
)
INTERMISSION_MANIFEST_PATH = (
    PROJECT_ROOT
    / "manifests/ui-intermission-atlas-map-canary-validation.json"
)
INTERMISSION_ISO_CONFIG_PATH = (
    PROJECT_ROOT
    / "config/iso/ui-intermission-atlas-map-canary-build.json"
)
INTERMISSION_RUNTIME_MANIFEST_PATH = (
    PROJECT_ROOT
    / "manifests/ui-intermission-atlas-map-canary-runtime-validation.json"
)
INTERMISSION_COMPONENT_ROOT = (
    PROJECT_ROOT
    / "work/build/ui-intermission-atlas-map-canary/components"
)


def sha256_path(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


class UiAtlasMapCanaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cls.manifest = json.loads(
            MANIFEST_PATH.read_text(encoding="utf-8")
        )
        cls.iso_config = load_config(ISO_CONFIG_PATH)
        cls.runtime_manifest = json.loads(
            RUNTIME_MANIFEST_PATH.read_text(encoding="utf-8")
        )
        cls.intermission_config = json.loads(
            INTERMISSION_CONFIG_PATH.read_text(encoding="utf-8")
        )
        cls.intermission_manifest = json.loads(
            INTERMISSION_MANIFEST_PATH.read_text(encoding="utf-8")
        )
        cls.intermission_iso_config = load_config(
            INTERMISSION_ISO_CONFIG_PATH
        )
        cls.intermission_runtime_manifest = json.loads(
            INTERMISSION_RUNTIME_MANIFEST_PATH.read_text(
                encoding="utf-8"
            )
        )

    def test_mask_rejects_geometry_outside_picture(self):
        with self.assertRaisesRegex(
            UiAtlasCanaryError,
            "exceeds",
        ):
            AtlasMask.from_mapping(
                {
                    "x": 250,
                    "y": 0,
                    "width": 16,
                    "height": 16,
                    "replacement_rgba": "00000000",
                    "preserve_rgba": ["00000000"],
                }
            )

    def test_rgba_audit_rejects_change_outside_mask(self):
        original = bytes(256 * 256 * 4)
        mask = AtlasMask.from_mapping(
            {
                "x": 0,
                "y": 0,
                "width": 16,
                "height": 16,
                "replacement_rgba": "01020304",
                "preserve_rgba": ["01020304"],
            }
        )
        edited = bytearray(apply_masked_rgba(original, mask))
        edited[(20 * 256 + 20) * 4 : (20 * 256 + 20) * 4 + 4] = (
            b"\x01\x02\x03\x04"
        )
        with self.assertRaisesRegex(
            UiAtlasCanaryError,
            "escaped",
        ):
            verify_masked_rgba(original, bytes(edited), mask)

    def test_rgba_audit_accepts_one_bounded_replacement(self):
        original = bytearray(256 * 256 * 4)
        start = (5 * 256 + 6) * 4
        original[start : start + 4] = b"\x10\x20\x30\x40"
        edited = bytearray(original)
        edited[start : start + 4] = b"\x00\x00\x00\x00"
        mask = AtlasMask.from_mapping(
            {
                "x": 6,
                "y": 5,
                "width": 2,
                "height": 1,
                "replacement_rgba": "00000000",
                "preserve_rgba": ["00000000"],
            }
        )
        report = verify_masked_rgba(
            bytes(original),
            bytes(edited),
            mask,
        )
        self.assertEqual(report["changed_pixel_count"], 1)
        self.assertTrue(report["outside_mask_rgba_exact"])
        self.assertTrue(report["replacement_rgba_exact"])
        self.assertTrue(report["preserved_rgba_exact"])

    def test_mask_preserves_multiple_registered_background_colors(self):
        opaque_black = b"\x00\x00\x00\xff"
        transparent_black = b"\x00\x00\x00\x00"
        glyph = b"\x70\x70\x70\xff"
        original = bytearray(opaque_black * (256 * 256))
        original[0:4] = transparent_black
        original[4:8] = glyph
        mask = AtlasMask.from_mapping(
            {
                "x": 0,
                "y": 0,
                "width": 3,
                "height": 1,
                "replacement_rgba": "000000ff",
                "preserve_rgba": ["000000ff", "00000000"],
            }
        )
        edited = apply_masked_rgba(bytes(original), mask)
        self.assertEqual(edited[0:4], transparent_black)
        self.assertEqual(edited[4:8], opaque_black)
        report = verify_masked_rgba(bytes(original), edited, mask)
        self.assertEqual(report["changed_pixel_count"], 1)
        self.assertEqual(report["preserved_pixel_count"], 2)
        self.assertEqual(
            report["preserved_rgba_counts"],
            {
                "000000ff": 1,
                "00000000": 1,
            },
        )

    def test_rgba_audit_rejects_preserved_color_missing_from_mask(self):
        original = bytearray(b"\x00\x00\x00\xff" * (256 * 256))
        original[0:4] = b"\x70\x70\x70\xff"
        mask = AtlasMask.from_mapping(
            {
                "x": 0,
                "y": 0,
                "width": 1,
                "height": 1,
                "replacement_rgba": "000000ff",
                "preserve_rgba": ["000000ff", "00000000"],
            }
        )
        edited = apply_masked_rgba(bytes(original), mask)
        with self.assertRaisesRegex(
            UiAtlasCanaryError,
            "does not contain preserved RGBA",
        ):
            verify_masked_rgba(bytes(original), edited, mask)

    def test_component_manifest_keeps_mapping_runtime_pending(self):
        self.assertEqual(
            self.manifest["status"],
            "static_component_validated_runtime_mapping_pending",
        )
        self.assertEqual(self.manifest["target"]["chunk_index"], 2)
        self.assertEqual(
            self.manifest["target"]["mask"],
            self.config["target"]["mask"],
        )
        self.assertEqual(
            self.manifest["target"]["semantic_locator"],
            "SHIP",
        )
        self.assertEqual(
            self.manifest["target"]["operation"],
            "erase_non_background_pixels",
        )
        self.assertEqual(
            self.manifest["target"]["candidate_scene_ids"],
            [
                "information/unit-pilot-mech-core",
                "search/filter-and-results",
                "battle/map-and-tactical",
            ],
        )
        self.assertEqual(
            self.manifest["injection"]["changed_pixel_count"],
            299,
        )
        self.assertEqual(
            self.manifest["target"]["mask_audit"][
                "preserved_rgba_counts"
            ],
            {"00000000": 485},
        )
        self.assertEqual(
            self.manifest["injection"]["archive_diff"]["diff_count"],
            185,
        )
        self.assertTrue(all(self.manifest["acceptance"].values()))
        self.assertEqual(
            self.manifest["runtime"]["status"],
            "not_tested",
        )

    def test_component_and_previews_match_output_locks(self):
        paths = {
            "archive": COMPONENT_ROOT / "KURODATA/KVMDATA.BIN",
            "reference_png": (
                PROJECT_ROOT
                / self.config["outputs"]["reference_png"]
            ),
            "edited_png": (
                PROJECT_ROOT / self.config["outputs"]["edited_png"]
            ),
        }
        for name, path in paths.items():
            expected = self.config["expected"][name]
            self.assertEqual(path.stat().st_size, expected["size"])
            self.assertEqual(sha256_path(path), expected["sha256"])

    def test_iso_contract_uses_only_the_component_archive(self):
        replacements = self.iso_config["replacements"]
        self.assertEqual(len(replacements), 1)
        replacement = replacements[0]
        self.assertEqual(
            replacement["member"],
            self.manifest["target"]["member"],
        )
        self.assertEqual(
            {
                "size": replacement["size"],
                "sha256": replacement["sha256"],
            },
            self.manifest["outputs"]["archive"],
        )
        self.assertEqual(
            self.iso_config["layout"]["expected_shift_sectors"],
            0,
        )

    def test_static_iso_manifest_preserves_runtime_boundary(self):
        manifest = self.runtime_manifest
        self.assertEqual(
            manifest["status"],
            "static_mapping_iso_validated_runtime_not_tested",
        )
        self.assertEqual(manifest["runtime"]["status"], "not_tested")
        self.assertEqual(
            manifest["iso_build"]["output"],
            {
                "size": 3758358528,
                "sha256": (
                    "9343889dc72c6d3fc2287f0ac279912f"
                    "b1ae7e1e1123ee15150f667e50bc78f6"
                ),
            },
        )
        self.assertEqual(
            manifest["iso_build"]["unchanged_member_count"],
            65,
        )
        self.assertEqual(
            manifest["iso_build"]["shifted_member_count"],
            0,
        )
        self.assertTrue(all(manifest["static_acceptance"].values()))
        texture_delta = manifest["runtime"]["expected_texture_delta"]
        self.assertEqual(texture_delta["changed_pixel_count"], 299)
        self.assertEqual(
            texture_delta["mask"],
            self.config["target"]["mask"],
        )

    def test_intermission_component_is_bounded_and_runtime_pending(self):
        manifest = self.intermission_manifest
        self.assertEqual(
            manifest["status"],
            "static_component_validated_runtime_mapping_pending",
        )
        self.assertEqual(manifest["target"]["chunk_index"], 6)
        self.assertEqual(
            manifest["target"]["semantic_locator"],
            "インターミッション",
        )
        self.assertEqual(
            manifest["target"]["mask"],
            self.intermission_config["target"]["mask"],
        )
        self.assertEqual(
            manifest["target"]["mask_audit"]["changed_pixel_count"],
            803,
        )
        self.assertEqual(
            manifest["target"]["mask_audit"][
                "preserved_rgba_counts"
            ],
            {
                "000000ff": 4877,
                "00000000": 55,
            },
        )
        self.assertEqual(
            manifest["injection"]["archive_diff"]["diff_count"],
            509,
        )
        self.assertEqual(
            manifest["target"]["candidate_evidence_status"],
            (
                "upstream_changed_offline_visual_candidate_"
                "not_runtime_mapped"
            ),
        )
        self.assertEqual(
            manifest["target"]["candidate_scene_ids"],
            [
                "intermission/main-and-options",
                "information/unit-pilot-mech-core",
            ],
        )
        self.assertTrue(all(manifest["acceptance"].values()))
        self.assertEqual(manifest["runtime"]["status"], "not_tested")

    def test_intermission_component_and_previews_match_locks(self):
        paths = {
            "archive": (
                INTERMISSION_COMPONENT_ROOT / "KURODATA/KVMDATA.BIN"
            ),
            "reference_png": (
                PROJECT_ROOT
                / self.intermission_config["outputs"]["reference_png"]
            ),
            "edited_png": (
                PROJECT_ROOT
                / self.intermission_config["outputs"]["edited_png"]
            ),
        }
        for name, path in paths.items():
            expected = self.intermission_config["expected"][name]
            self.assertEqual(path.stat().st_size, expected["size"])
            self.assertEqual(sha256_path(path), expected["sha256"])

    def test_intermission_iso_is_single_member_and_runtime_pending(self):
        iso_config = self.intermission_iso_config
        replacements = iso_config["replacements"]
        self.assertEqual(len(replacements), 1)
        self.assertEqual(
            {
                "size": replacements[0]["size"],
                "sha256": replacements[0]["sha256"],
            },
            self.intermission_manifest["outputs"]["archive"],
        )
        runtime = self.intermission_runtime_manifest
        self.assertEqual(
            runtime["status"],
            "static_mapping_iso_validated_runtime_not_tested",
        )
        self.assertEqual(
            runtime["iso_build"]["output"],
            {
                "size": 3758358528,
                "sha256": (
                    "dafe4737f797b611e02a0dcf68096a40"
                    "e9b3c61ae4fa98d979b19a00ce0ca0df"
                ),
            },
        )
        self.assertEqual(runtime["iso_build"]["shifted_member_count"], 0)
        self.assertEqual(
            runtime["runtime"]["expected_texture_delta"][
                "changed_pixel_count"
            ],
            803,
        )
        self.assertEqual(runtime["runtime"]["status"], "not_tested")


if __name__ == "__main__":
    unittest.main()
