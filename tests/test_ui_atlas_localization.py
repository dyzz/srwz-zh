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
from tools.srwz.tim2 import parse_tim2


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
PROFILES = {
    "info": {
        "stem": "ui-info-atlas-zh",
        "archive_sha256": (
            "bf31697f19bca40446bf089374c4a6ef7cb1ec29a1e7a3f68c7eb0c00f321b6b"
        ),
        "character_count": 2,
        "added_pixel_count": 264,
        "changed_pixel_count": 414,
    },
    "battle-command": {
        "stem": "ui-battle-command-atlas-zh",
        "archive_sha256": (
            "68fafca4b120667b15514a48a4999affc2799438540e2998a037dea48dbb5bdc"
        ),
        "character_count": 4,
        "added_pixel_count": 554,
        "changed_pixel_count": 2332,
    },
    "bazaar": {
        "stem": "ui-bazaar-atlas-zh",
        "archive_sha256": (
            "54670e0d0a1340dd297d2c531e6f8180796717d4651c7525e735ed0cc92baadc"
        ),
        "character_count": 3,
        "added_pixel_count": 2603,
        "changed_pixel_count": 3704,
    },
    "intermission": {
        "stem": "ui-intermission-atlas-zh",
        "archive_sha256": (
            "3d9ab911ebe65eb0fad5d0afaae031f4c70170d821a1d7a014dfe3aaae8d152b"
        ),
        "character_count": 4,
        "added_pixel_count": 5467,
        "changed_pixel_count": 10563,
    },
    "formation": {
        "stem": "ui-formation-atlas-zh",
        "archive_sha256": (
            "d5ce2a06be0b407005a353d56c0543bca0e29187b545e09b1deeb97fa37b6dd8"
        ),
        "character_count": 4,
        "added_pixel_count": 1923,
        "changed_pixel_count": 3270,
    },
    "stage-clear": {
        "stem": "ui-stage-clear-atlas-zh",
        "archive_sha256": (
            "ba3f2fad9351294402e3488b66edf7d3a211818efd3ce58a96e25f17bffee13f"
        ),
        "character_count": 4,
        "added_pixel_count": 469,
        "changed_pixel_count": 689,
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
            cls.profiles[name] = {
                **expected,
                "config_path": config_path,
                "config": json.loads(config_path.read_text(encoding="utf-8")),
                "manifest": json.loads(
                    manifest_path.read_text(encoding="utf-8")
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

    def test_all_production_atlas_text_uses_frozen_four_x_renders(self):
        for name, profile in self.profiles.items():
            with self.subTest(profile=name):
                config = profile["config"]
                labels = [
                    config["localized_label"],
                    *config.get("additional_localized_labels", []),
                ]
                self.assertTrue(labels)
                self.assertTrue(
                    all(
                        label["render"]["supersample_factor"] == 4
                        for label in labels
                    )
                )
                snapshot = config["render_snapshot"]
                self.assertTrue(snapshot["path"].endswith("-render-snapshot.json"))
                self.assertGreater(snapshot["size"], 0)
                self.assertEqual(len(snapshot["sha256"]), 64)
                self.assertEqual(
                    profile["manifest"]["toolchain"]["text_render_source"],
                    "locked_snapshot",
                )
                self.assertTrue(
                    profile["manifest"]["acceptance"][
                        "frozen_render_snapshot_consumed"
                    ]
                )

    def test_intermission_uses_frozen_supersampled_pixel_aligned_italic_renders(self):
        manifest = self.profiles["intermission"]["manifest"]
        config = self.profiles["intermission"]["config"]
        self.assertEqual(config["replacement_mode"], "fixed_source_elements")
        self.assertEqual(config["expected_background_palette_index"], 0)
        labels = [config["localized_label"], *config["additional_localized_labels"]]
        self.assertEqual(len(labels), 9)
        self.assertEqual(
            len({label["source_element_id"] for label in labels}),
            len(labels),
        )
        self.assertTrue(
            all(
                label["render"]["italic_shear_degrees"] == 12
                for label in labels
            )
        )
        self.assertTrue(
            all(
                label["render"]["supersample_factor"] == 4
                for label in labels
            )
        )
        self.assertEqual(
            labels[0]["render"]["indexed_layers"],
            labels[1]["render"]["indexed_layers"],
        )
        self.assertEqual(
            [
                entry["palette_index"]
                for entry in labels[1]["render"]["indexed_layers"][
                    "outline"
                ]
            ],
            list(range(1, 8)),
        )
        self.assertEqual(
            [
                entry["palette_index"]
                for entry in labels[1]["render"]["indexed_layers"]["fill"]
            ],
            list(range(8, 16)),
        )
        self.assertTrue(
            all(
                label["render"]["indexed_layer_profile"] == "menu"
                for label in labels[2:]
            )
        )
        self.assertEqual(
            [
                entry["palette_index"]
                for entry in config["indexed_text_layer_profiles"]["menu"][
                    "fill"
                ]
            ],
            list(range(8, 15)),
        )
        self.assertTrue(
            all(
                label["render"]["stroke_width"] == 0.25
                for label in labels[2:]
            )
        )
        self.assertEqual(
            config["render_snapshot"]["path"],
            "config/assets/ui-intermission-atlas-render-snapshot.json",
        )
        self.assertEqual(
            manifest["toolchain"]["text_render_source"],
            "locked_snapshot",
        )
        self.assertTrue(
            manifest["acceptance"]["frozen_render_snapshot_consumed"]
        )
        base_mapping = json.loads(
            (
                PROJECT_ROOT
                / config["base_mapping"]["config"]
            ).read_text(encoding="utf-8")
        )
        masks = [
            base_mapping["target"]["mask"],
            *(label["mask"] for label in labels[1:]),
        ]
        self.assertTrue(
            all(
                mask["replacement_rgba"] == "000000ff"
                and mask["preserve_rgba"] == ["000000ff"]
                for mask in masks
            )
        )
        translations = {
            entry["id"]: entry["translation"]
            for entry in json.loads(
                (
                    PROJECT_ROOT
                    / config["localized_label"]["translation_source"][
                        "path"
                    ]
                ).read_text(encoding="utf-8")
            )["entries"]
        }
        self.assertEqual(translations["ui-atlas/kvm6/unit-category"], "机体")
        self.assertEqual(translations["ui-atlas/kvm6/pilot-category"], "机师")
        self.assertEqual(translations["ui-atlas/kvm6/bazaar"], "集市")
        self.assertEqual(
            translations["ui-atlas/kvm6/squad-formation"],
            "小队",
        )
        self.assertTrue(
            manifest["acceptance"][
                "source_element_rectangles_and_rgba_locked"
            ]
        )
        self.assertTrue(
            manifest["acceptance"][
                "fixed_element_palette_indexes_rebuilt"
            ]
        )
        self.assertTrue(
            manifest["acceptance"][
                "indexed_outline_and_fill_layers_rebuilt"
            ]
        )
        self.assertEqual(
            manifest["target"]["expected_background_palette_index"],
            0,
        )
        source_elements = manifest["text_audit"]["source_elements"]
        self.assertEqual(len(source_elements), len(labels))
        self.assertEqual(
            [(item["width"], item["height"]) for item in source_elements],
            [
                (215, 31),
                (218, 29),
                (69, 27),
                (99, 27),
                (63, 22),
                (100, 22),
                (101, 25),
                (88, 22),
                (111, 25),
            ],
        )
        archive = (
            PROJECT_ROOT
            / config["outputs"]["component_root"]
            / config["target"]["member"]
        ).read_bytes()
        chunk = archive[
            manifest["target"]["chunk_start"] :
            manifest["target"]["chunk_end"]
        ]
        picture = parse_tim2(chunk).pictures[0]
        image_start = picture.offset + picture.header_size
        packed = chunk[image_start : image_start + picture.image_size]
        indexes = bytes(
            value
            for packed_byte in packed
            for value in (packed_byte & 0x0F, packed_byte >> 4)
        )
        for mask_index, current_mask in enumerate(masks):
            source_indexes = {
                indexes[y * 256 + x]
                for y in range(
                    current_mask["y"],
                    current_mask["y"] + current_mask["height"],
                )
                for x in range(
                    current_mask["x"],
                    current_mask["x"] + current_mask["width"],
                )
            }
            self.assertTrue(source_indexes & set(range(1, 8)))
            self.assertTrue(source_indexes & set(range(8, 15)))
            if mask_index in {0, 1}:
                self.assertIn(15, source_indexes)
            else:
                self.assertNotIn(15, source_indexes)
            self.assertIn(0, source_indexes)

    def test_stage_clear_replaces_only_the_fixed_suffix(self):
        profile = self.profiles["stage-clear"]
        config = profile["config"]
        manifest = profile["manifest"]
        base_mapping = json.loads(
            (
                PROJECT_ROOT / config["base_mapping"]["config"]
            ).read_text(encoding="utf-8")
        )
        translation_source = json.loads(
            (
                PROJECT_ROOT
                / config["localized_label"]["translation_source"]["path"]
            ).read_text(encoding="utf-8")
        )

        self.assertEqual(config["target"]["chunk_index"], 11)
        self.assertEqual(
            base_mapping["target"]["mask"],
            {
                "x": 60,
                "y": 0,
                "width": 94,
                "height": 24,
                "replacement_rgba": "00000000",
                "preserve_rgba": ["00000000"],
            },
        )
        self.assertEqual(
            translation_source["entries"][0]["translation"],
            "已通关！",
        )
        self.assertEqual(
            config["localized_label"]["render"]["horizontal_offset"],
            -16,
        )
        self.assertEqual(
            manifest["localized_label"]["render"]["horizontal_offset"],
            -16,
        )
        self.assertTrue(
            manifest["acceptance"][
                "source_element_rectangles_and_rgba_locked"
            ]
        )
        self.assertTrue(
            manifest["target"]["mask_audit"]["outside_mask_rgba_exact"]
        )

    def test_formation_labels_rebuild_the_full_background_index(self):
        profile = self.profiles["formation"]
        config = profile["config"]
        manifest = profile["manifest"]
        squad_group = next(
            label
            for label in config["additional_localized_labels"]
            if label["semantic_locator"] == "小隊群へ"
        )

        self.assertEqual(squad_group["mask"], {
            "x": 44,
            "y": 178,
            "width": 67,
            "height": 22,
            "replacement_rgba": "00000000",
            "preserve_rgba": ["00000000"],
        })
        self.assertTrue(config["force_reindex_entire_masks"])
        self.assertEqual(config["expected_background_palette_index"], 0)
        self.assertTrue(manifest["target"]["force_reindex_entire_masks"])
        self.assertEqual(
            manifest["target"]["expected_background_palette_index"],
            0,
        )
        self.assertTrue(
            manifest["acceptance"][
                "mask_background_palette_index_rebuilt"
            ]
        )

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

if __name__ == "__main__":
    unittest.main()
