import json
import unittest
from pathlib import Path

from tools.build_full_story_components import build


PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMPONENT_CONFIG = PROJECT_ROOT / "config/full-story-components.json"
COMPONENT_MANIFEST = (
    PROJECT_ROOT / "manifests/full-story-components-validation.json"
)
FONT_MANIFEST = PROJECT_ROOT / "manifests/zh-release-font-validation.json"
ISO_CONFIG = PROJECT_ROOT / "config/iso/ui-p10-full-story-build.json"
ISO_CONTENT_MANIFEST = (
    PROJECT_ROOT / "manifests/full-story-iso-content-validation.json"
)
RUNTIME_MANIFEST = (
    PROJECT_ROOT / "manifests/runtime/ui-p10-full-story-stage-entry.json"
)


class FullStoryIsoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.component_config = json.loads(
            COMPONENT_CONFIG.read_text(encoding="utf-8")
        )
        cls.component = json.loads(
            COMPONENT_MANIFEST.read_text(encoding="utf-8")
        )
        cls.font = json.loads(FONT_MANIFEST.read_text(encoding="utf-8"))
        cls.iso_config = json.loads(ISO_CONFIG.read_text(encoding="utf-8"))
        cls.iso_content = json.loads(
            ISO_CONTENT_MANIFEST.read_text(encoding="utf-8")
        )
        cls.runtime = json.loads(
            RUNTIME_MANIFEST.read_text(encoding="utf-8")
        )

    def test_component_rebuild_and_seven_outputs_are_exact(self):
        output_root = (
            PROJECT_ROOT
            / self.component_config["outputs"]["component_root"]
        )
        payloads, report = build(COMPONENT_CONFIG, output_root)
        self.assertEqual(report, self.component)
        self.assertEqual(len(payloads), 7)
        for member, payload in payloads.items():
            self.assertEqual(
                (PROJECT_ROOT / report["outputs"][member]["path"])
                .read_bytes(),
                payload,
            )

    def test_full_story_font_and_stage_ratchets_are_explicit(self):
        coverage = self.font["coverage"]
        self.assertEqual(
            self.font["inputs"]["translation_selection"][
                "unique_entry_count"
            ],
            94090,
        )
        self.assertEqual(coverage["missing_character_count"], 0)
        self.assertEqual(coverage["original_font_han_count"], 0)
        self.assertEqual(
            coverage["original_font_visible_character_count"],
            0,
        )
        self.assertEqual(
            self.font["mapping"]["primary_assignment_count"],
            3178,
        )
        self.assertEqual(
            self.font["mapping"]["surface_alias_assignment_count"],
            701,
        )
        self.assertEqual(
            coverage["preserved_raw_ascii_punctuation_characters"],
            '"%&\',-./:=~',
        )
        self.assertEqual(self.component["story"]["stage_count"], 154)
        self.assertEqual(
            self.component["story"]["translated_allocation_count"],
            83277,
        )
        self.assertEqual(self.component["story"]["speaker_count"], 8469)
        self.assertEqual(
            self.component["story"]["minimum_compressed_chunk_headroom"],
            22,
        )
        self.assertTrue(all(self.component["acceptance"].values()))

    def test_iso_config_remains_bound_to_the_historical_runtime_snapshot(self):
        replacements = {
            item["member"]: {
                "path": item["source"],
                "size": item["size"],
                "sha256": item["sha256"],
            }
            for item in self.iso_config["replacements"]
        }
        historical = {
            member: {
                "size": lock["size"],
                "sha256": lock["sha256"],
            }
            for member, lock in self.iso_content["members"].items()
        }
        self.assertEqual(
            {
                member: {"size": lock["size"], "sha256": lock["sha256"]}
                for member, lock in replacements.items()
            },
            historical,
        )
        self.assertNotEqual(
            replacements["DATA/VT1.BIN"]["sha256"],
            self.component["outputs"]["DATA/VT1.BIN"]["sha256"],
        )
        self.assertNotEqual(
            replacements["KURODATA/KVMDATA.BIN"]["sha256"],
            self.component["outputs"]["KURODATA/KVMDATA.BIN"]["sha256"],
        )
        self.assertNotEqual(
            self.iso_config["component_required_status"],
            self.component["status"],
        )
        self.assertEqual(
            self.iso_config["component_required_status"],
            "integrated_p10_ui_full_story_components_validated_runtime_pending",
        )
        self.assertEqual(
            self.iso_config["output"]["expected_sha256"],
            "21b00c2de1d25ca668f21b1c9d95486c223aa7f55d610d684495ca463eead4cc",
        )
        self.assertTrue(
            self.iso_config["layout"][
                "preserve_original_member_sector_allocations"
            ]
        )
        self.assertTrue(
            all(
                segment["shift_sectors"] == 0
                for segment in self.iso_config["layout"]["shift_segments"]
            )
        )
        self.assertEqual(
            self.iso_config["output"]["expected_size"],
            self.iso_config["source_iso"]["size"],
        )
        self.assertEqual(replacements["DATA/VT1.BIN"]["size"], 127500736)

    def test_final_iso_readback_covers_every_story_entry(self):
        manifest = self.iso_content
        self.assertEqual(
            manifest["status"],
            "full_story_final_iso_static_content_readback_passed",
        )
        self.assertEqual(manifest["stage_count"], 154)
        self.assertEqual(manifest["translation_entry_count"], 91746)
        self.assertEqual(manifest["dialogue_count"], 82719)
        self.assertEqual(manifest["condition_count"], 558)
        self.assertEqual(manifest["speaker_count"], 8469)
        self.assertTrue(all(manifest["checks"].values()))
        self.assertEqual(
            manifest["iso"]["sha256"],
            self.iso_config["output"]["expected_sha256"],
        )
        visible_ascii = manifest["visible_ascii_policy"]
        self.assertEqual(visible_ascii["stock_alphanumeric_glyph_count"], 62)
        self.assertTrue(visible_ascii["stock_alphanumeric_glyphs_byte_exact"])
        self.assertTrue(
            visible_ascii["raw_and_fullwidth_codes_share_glyph_slots"]
        )
        self.assertEqual(
            set(visible_ascii["story_storage_examples"]),
            {"ZAFT", "PLANT"},
        )
        self.assertEqual(
            set(manifest["compdata"]["unit_ascii_storage_examples"]),
            {"LS", "WM"},
        )

    def test_current_iso_requires_fresh_runtime_promotion(self):
        self.assertEqual(
            self.iso_config["runtime_evidence_manifest"],
            RUNTIME_MANIFEST.relative_to(PROJECT_ROOT).as_posix(),
        )
        self.assertEqual(self.runtime["status"], "passed")
        self.assertNotEqual(
            self.runtime["iso"]["sha256"],
            self.iso_config["output"]["expected_sha256"],
        )
        self.assertEqual(
            self.runtime["iso"]["size"],
            self.iso_config["output"]["expected_size"],
        )
        self.assertEqual(
            [route["route_id"] for route in self.runtime["routes"]],
            [
                "load-page-1-last-save-to-stage-37",
                "new-game-default-male-to-first-stage",
            ],
        )
        self.assertEqual(
            self.iso_content["runtime_acceptance"],
            "static final-ISO content readback; fresh PCSX2 runtime evidence "
            "is separate",
        )


if __name__ == "__main__":
    unittest.main()
