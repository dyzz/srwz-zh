import hashlib
import json
import unittest
from pathlib import Path

from tools.srwz.ui_atlas_canary import (
    AtlasMask,
    UiAtlasCanaryError,
    apply_masked_rgba,
    build_ui_atlas_map_canary,
    verify_masked_rgba,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROFILE_CASES = (
    {
        "name": "information",
        "config": "config/assets/maps/tim2-kvm2-info.json",
        "manifest": (
            "manifests/ui-info-atlas-map-canary-validation.json"
        ),
        "chunk_index": 2,
        "semantic_locator": "SHIP",
        "candidate_evidence_status": (
            "offline_visual_candidate_not_runtime_mapped"
        ),
        "candidate_scene_ids": [
            "information/unit-pilot-mech-core",
            "search/filter-and-results",
            "battle/map-and-tactical",
        ],
        "changed_pixel_count": 299,
        "preserved_rgba_counts": {"00000000": 485},
        "changed_archive_byte_count": 185,
    },
    {
        "name": "battle-command",
        "config": (
            "config/assets/maps/tim2-kvm4-battle-command.json"
        ),
        "manifest": (
            "manifests/"
            "ui-battle-command-atlas-map-canary-validation.json"
        ),
        "chunk_index": 4,
        "semantic_locator": "COMMAND MENU",
        "candidate_evidence_status": (
            "offline_visual_candidate_not_runtime_mapped"
        ),
        "candidate_scene_ids": [
            "battle/map-and-tactical",
            "results/level-up-and-deployment",
        ],
        "changed_pixel_count": 2297,
        "preserved_rgba_counts": {"00000000": 491},
        "changed_archive_byte_count": 1221,
    },
    {
        "name": "bazaar",
        "config": "config/assets/maps/tim2-kvm5-bazaar.json",
        "manifest": (
            "manifests/ui-bazaar-atlas-map-canary-validation.json"
        ),
        "chunk_index": 5,
        "semantic_locator": "バザー",
        "candidate_evidence_status": (
            "upstream_changed_offline_visual_candidate_"
            "not_runtime_mapped"
        ),
        "candidate_scene_ids": [
            "intermission/main-and-options",
        ],
        "changed_pixel_count": 2197,
        "preserved_rgba_counts": {"00000000": 6160},
        "changed_archive_byte_count": 1210,
    },
    {
        "name": "intermission",
        "config": (
            "config/assets/maps/tim2-kvm6-intermission.json"
        ),
        "manifest": (
            "manifests/"
            "ui-intermission-atlas-map-canary-validation.json"
        ),
        "chunk_index": 6,
        "semantic_locator": "インターミッション",
        "candidate_evidence_status": (
            "upstream_changed_offline_visual_candidate_"
            "not_runtime_mapped"
        ),
        "candidate_scene_ids": [
            "intermission/main-and-options",
            "information/unit-pilot-mech-core",
        ],
        "changed_pixel_count": 982,
        "preserved_rgba_counts": {"000000ff": 5708},
        "changed_archive_byte_count": 593,
    },
    {
        "name": "formation",
        "config": "config/assets/maps/tim2-kvm7-formation.json",
        "manifest": (
            "manifests/ui-formation-atlas-map-canary-validation.json"
        ),
        "chunk_index": 7,
        "semantic_locator": "新規編成",
        "candidate_evidence_status": (
            "offline_visual_candidate_not_runtime_mapped"
        ),
        "candidate_scene_ids": [
            "intermission/main-and-options",
            "results/level-up-and-deployment",
        ],
        "changed_pixel_count": 1325,
        "preserved_rgba_counts": {"00000000": 155},
        "changed_archive_byte_count": 691,
    },
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
        cls.profiles = []
        for raw_case in PROFILE_CASES:
            case = dict(raw_case)
            config_path = PROJECT_ROOT / case["config"]
            manifest_path = PROJECT_ROOT / case["manifest"]
            config = json.loads(
                config_path.read_text(encoding="utf-8")
            )
            case.update(
                {
                    "config_path": config_path,
                    "config_data": config,
                    "manifest_data": json.loads(
                        manifest_path.read_text(encoding="utf-8")
                    ),
                    "component_root": (
                        PROJECT_ROOT
                        / config["outputs"]["component_root"]
                    ),
                }
            )
            cls.profiles.append(case)

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

    def test_components_are_bounded_and_runtime_pending(self):
        for case in self.profiles:
            with self.subTest(profile=case["name"]):
                config = case["config_data"]
                manifest = case["manifest_data"]
                self.assertEqual(
                    manifest["status"],
                    (
                        "static_component_validated_"
                        "runtime_mapping_pending"
                    ),
                )
                self.assertEqual(
                    manifest["target"]["chunk_index"],
                    case["chunk_index"],
                )
                self.assertEqual(
                    manifest["target"]["semantic_locator"],
                    case["semantic_locator"],
                )
                self.assertEqual(
                    manifest["target"]["mask"],
                    config["target"]["mask"],
                )
                self.assertEqual(
                    manifest["target"]["operation"],
                    "erase_non_background_pixels",
                )
                self.assertEqual(
                    manifest["target"]["candidate_evidence_status"],
                    case["candidate_evidence_status"],
                )
                self.assertEqual(
                    manifest["target"]["candidate_scene_ids"],
                    case["candidate_scene_ids"],
                )
                self.assertEqual(
                    manifest["injection"]["changed_pixel_count"],
                    case["changed_pixel_count"],
                )
                self.assertEqual(
                    manifest["target"]["mask_audit"][
                        "preserved_rgba_counts"
                    ],
                    case["preserved_rgba_counts"],
                )
                self.assertEqual(
                    manifest["injection"]["archive_diff"][
                        "diff_count"
                    ],
                    case["changed_archive_byte_count"],
                )
                self.assertTrue(all(manifest["acceptance"].values()))
                self.assertEqual(
                    manifest["runtime"]["status"],
                    "not_tested",
                )

    def test_components_and_previews_match_output_locks(self):
        for case in self.profiles:
            with self.subTest(profile=case["name"]):
                config = case["config_data"]
                payloads, _report = build_ui_atlas_map_canary(
                    PROJECT_ROOT,
                    case["config_path"],
                )
                for name, payload in payloads.items():
                    expected = config["expected"][name]
                    self.assertEqual(
                        len(payload),
                        expected["size"],
                    )
                    self.assertEqual(
                        hashlib.sha256(payload).hexdigest(),
                        expected["sha256"],
                    )

if __name__ == "__main__":
    unittest.main()
