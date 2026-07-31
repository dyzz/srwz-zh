import json
import unittest
from pathlib import Path

from tools.srwz.ui_test_candidate import build_ui_test_candidate


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_CONFIG = (
    PROJECT_ROOT
    / "config/ui-integration/p2-default-names-first-five.json"
)
INTEGRATION_MANIFEST = (
    PROJECT_ROOT
    / "manifests/ui-p2-default-names-first-five-validation.json"
)
STORY_MANIFEST = PROJECT_ROOT / "manifests/first-five-rust-validation.json"
STORY_REPORT = (
    PROJECT_ROOT
    / "work/build/first-five-rust/components/component-validation.json"
)
RUNTIME_MANIFEST = (
    PROJECT_ROOT
    / "manifests/ui-p2-default-names-first-five-runtime-validation.json"
)
ISO_REPORT = (
    PROJECT_ROOT
    / "build/iso/ui-p2-default-names-first-five/iso-validation.json"
)
ISO_PATH = (
    PROJECT_ROOT
    / "build/iso/ui-p2-default-names-first-five/"
    "srwz-ui-p2-default-names-first-five.iso"
)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))

class UiP2DefaultNamesFirstFiveTests(unittest.TestCase):
    def test_default_values_are_localized_without_replacing_story_token(self):
        hidden_defaults = load_json(
            PROJECT_ROOT / "corpus/zh/menu/unclassified.json"
        )
        actual = {
            entry["id"]: entry["translation"]
            for entry in hidden_defaults["entries"]
            if entry["id"]
            in {
                "menu/SLPS/00/0071",
                "menu/SLPS/00/0072",
                "menu/SLPS/00/0073",
            }
        }
        self.assertEqual(
            actual,
            {
                "menu/SLPS/00/0071": "钢狮",
                "menu/SLPS/00/0072": "节子",
                "menu/SLPS/00/0073": "小原",
            },
        )
        name_screen = load_json(
            PROJECT_ROOT / "corpus/zh/menu/system-ui-name-screen.json"
        )
        actual_name_screen = {
            entry["id"]: entry["translation"]
            for entry in name_screen["entries"]
            if entry["id"]
            in {
                "menu/SLPS/01/0006",
                "menu/SLPS/01/0007",
                "menu/SLPS/01/0008",
                "menu/SLPS/01/0009",
            }
        }
        self.assertEqual(
            actual_name_screen,
            {
                "menu/SLPS/01/0006": "特拉维斯",
                "menu/SLPS/01/0007": "兰德",
                "menu/SLPS/01/0008": "小原",
                "menu/SLPS/01/0009": "节子",
            },
        )
        component = load_json(
            PROJECT_ROOT
            / "manifests/ui-p2-default-protagonist-names-validation.json"
        )
        base_reread = component["inputs"]["base_ui_core"][
            "required_localized_entries"
        ]
        self.assertEqual(base_reread["entry_count"], 4)
        self.assertEqual(base_reread["target_count"], 10)
        self.assertTrue(base_reread["reread_exact"])
        token_count = 0
        for stage in range(1, 6):
            document = load_json(
                PROJECT_ROOT
                / f"corpus/zh/story-dialogue/stage-{stage:03d}.json"
            )
            token_count += sum(
                entry["translation"].count("$n")
                for entry in document["entries"]
            )
        self.assertEqual(token_count, 17)
        self.assertEqual(
            load_json(STORY_MANIFEST)["translation_surface"][
                "runtime_player_name_token_count"
            ],
            token_count,
        )

    def test_rust_story_streams_round_trip_inside_original_chunk_spans(self):
        report = load_json(STORY_REPORT)
        self.assertEqual(report["stage_indices"], [1, 2, 3, 4, 5])
        self.assertTrue(report["stage_layout_preserved"])
        self.assertTrue(report["hb_offset_reread_exact"])
        self.assertEqual(report["unchanged_chunk_count"], 200)
        self.assertNotIn("pre_story_flow", report)
        self.assertNotIn("hsfc", report["outputs"])
        for stage in report["stages"]:
            self.assertEqual(
                stage["codec_strategy"],
                "preserved_prefix_rust-maximum_suffix",
            )
            self.assertLessEqual(
                stage["output_encoded_size"],
                stage["source_chunk_size"],
            )
            self.assertEqual(
                stage["output_chunk_size"],
                stage["source_chunk_size"],
            )
            self.assertTrue(stage["chunk_span_preserved"])
            self.assertTrue(stage["codec_round_trip_exact"])
            self.assertTrue(stage["translated_reread_exact"])

    def test_six_member_composition_is_deterministic_and_atlas_free(self):
        payloads, report = build_ui_test_candidate(
            PROJECT_ROOT,
            INTEGRATION_CONFIG,
        )
        self.assertEqual(report, load_json(INTEGRATION_MANIFEST))
        self.assertEqual(len(payloads), 6)
        self.assertTrue(report["acceptance"]["atlas_component_excluded"])
        self.assertFalse(
            report["runtime"][
                "isolated_atlas_mapping_profiles_remain_required"
            ]
        )

    def test_exact_iso_has_zero_lba_shifts_and_passed_boot_smoke(self):
        runtime = load_json(RUNTIME_MANIFEST)
        iso_report = load_json(ISO_REPORT)
        self.assertEqual(
            runtime["status"],
            "integrated_iso_boot_smoke_passed_visual_pending",
        )
        self.assertEqual(runtime["iso_build"]["shifted_member_count"], 0)
        self.assertEqual(runtime["runtime"]["pine_state"], "Running")
        self.assertEqual(runtime["runtime"]["tlb_miss_count"], 0)
        self.assertEqual(
            runtime["iso_build"]["output"]["size"],
            3758358528,
        )
        self.assertEqual(
            runtime["iso_build"]["output"]["sha256"],
            "026f29e3e77b78a19f000c6781317ebc95aeb672b5b2848ad2a30bf8d2f5c473",
        )
        self.assertNotIn(
            "stage_001_pre_story_world_map_location_acceptance",
            runtime["runtime"]["pending_gates"],
        )
        self.assertTrue(ISO_PATH.is_file())
        self.assertTrue(iso_report["layout"]["unchanged_member_bytes_exact"])
        self.assertTrue(iso_report["layout"]["replacement_bytes_exact"])
        self.assertEqual(
            sorted((PROJECT_ROOT / "build/iso").rglob("*.iso")),
            [ISO_PATH],
        )


if __name__ == "__main__":
    unittest.main()
