import hashlib
import json
import unittest
from pathlib import Path

from tools.srwz.codec import decode
from tools.srwz.iso_layout import (
    CORE_ARCHIVE_SPECS,
    read_executable_archive_offsets,
)
from tools.srwz.summary import parse_summary
from tools.srwz.text import augment_text_table, load_text_table
from tools.srwz.ui_menu import load_ui_font_overrides


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config/summary/world-history-component.json"
MANIFEST_PATH = PROJECT_ROOT / "manifests/ui-p1-world-history-validation.json"
RUNTIME_MANIFEST_PATH = (
    PROJECT_ROOT
    / "manifests/ui-p1-world-history-runtime-validation.json"
)
COMPONENT_ROOT = PROJECT_ROOT / "work/build/ui-p1-world-history/components"


class UiP1WorldHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        cls.runtime_manifest = json.loads(
            RUNTIME_MANIFEST_PATH.read_text(encoding="utf-8")
        )

    def test_complete_selection_and_allocation_ratchets(self):
        self.assertEqual(
            self.manifest["status"],
            "offline_component_validated_runtime_not_tested",
        )
        self.assertEqual(
            self.manifest["selection"]["translation_entry_count"],
            28,
        )
        self.assertEqual(
            self.manifest["fixed_allocations"]["write_operation_count"],
            28,
        )
        self.assertEqual(self.manifest["fixed_allocations"]["overflow_count"], 0)
        self.assertTrue(self.manifest["ratchet"]["passed"])
        self.assertEqual(self.config["codec"]["strategy"], "rust-maximum")
        self.assertEqual(
            self.manifest["ratchet"]["expected"],
            self.config["ratchet"],
        )

    def test_component_outputs_match_pinned_locks(self):
        paths = {
            "slps": COMPONENT_ROOT / "SLPS_258.87",
            "vt1": COMPONENT_ROOT / "DATA/VT1.BIN",
            "mtv_pros": COMPONENT_ROOT / "DATA/MTV_PROS.BIN",
        }
        for name, path in paths.items():
            payload = path.read_bytes()
            self.assertEqual(
                {
                    "size": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                },
                self.config["expected_outputs"][name],
            )

    def test_all_28_texts_reparse_exactly_from_all_14_chunks(self):
        font_manifest_path = (
            PROJECT_ROOT / self.config["font_candidate"]["manifest"]
        )
        font_manifest = json.loads(
            font_manifest_path.read_text(encoding="utf-8")
        )
        overrides, _ = load_ui_font_overrides(
            PROJECT_ROOT,
            self.config,
            font_manifest,
        )
        table = load_text_table(
            PROJECT_ROOT / self.config["source"]["text_table"]["path"]
        )
        output_table = augment_text_table(table, overrides)
        slps = (COMPONENT_ROOT / "SLPS_258.87").read_bytes()
        member = (COMPONENT_ROOT / "DATA/MTV_PROS.BIN").read_bytes()
        offsets = read_executable_archive_offsets(
            slps,
            CORE_ARCHIVE_SPECS["MTV_PROS.BIN"],
            len(member),
        )
        actual = {}
        for chunk_index, (start, end) in enumerate(zip(offsets, offsets[1:])):
            stream = member[start:end]
            result = decode(stream)
            self.assertFalse(any(stream[result.consumed :]))
            parsed = parse_summary(
                result.output,
                output_table,
                chunk_index=chunk_index,
            )
            self.assertEqual(parsed.unknown_code_count, 0)
            actual.update(
                {entry.entry_id: entry.text for entry in parsed.entries}
            )
        translations = json.loads(
            (
                PROJECT_ROOT
                / self.config["translation_source"]["path"]
            ).read_text(encoding="utf-8")
        )["entries"]
        self.assertEqual(
            actual,
            {entry["id"]: entry["translation"] for entry in translations},
        )

    def test_archive_and_slps_change_ownership_are_explicit(self):
        archive = self.manifest["archive"]
        self.assertEqual(archive["chunk_count"], 14)
        self.assertEqual(archive["changed_chunk_count"], 12)
        self.assertEqual(archive["unchanged_chunk_count"], 2)
        self.assertEqual(archive["decoded_round_trip_exact_count"], 14)
        self.assertEqual(archive["unknown_output_code_count"], 0)
        slps = self.manifest["slps_component"]
        self.assertEqual(slps["patch_plan"]["operation_count"], 1)
        self.assertTrue(slps["outside_offset_table_unchanged"])
        self.assertTrue(slps["offset_table_reread_exact"])
        self.assertEqual(
            slps["offset_table_end_exclusive"]
            - slps["offset_table_start"],
            60,
        )

    def test_p1_font_is_exact_and_runtime_is_not_overclaimed(self):
        self.assertTrue(
            self.manifest["vt1_component"]["p1_font_component_exact"]
        )
        self.assertEqual(
            self.manifest["inputs"]["font_component"][
                "selected_renderer_missing_character_count"
            ],
            0,
        )
        self.assertEqual(
            self.manifest["independent_reread"]["entry_count"],
            28,
        )
        self.assertTrue(
            self.manifest["independent_reread"]["all_texts_exact"]
        )
        self.assertEqual(self.manifest["runtime"]["status"], "not_tested")

    def test_static_iso_is_bound_without_overclaiming_runtime(self):
        runtime = self.runtime_manifest
        self.assertEqual(
            runtime["status"],
            "static_iso_validated_runtime_pending",
        )
        self.assertEqual(runtime["profile_id"], "ui-p1-world-history")
        self.assertEqual(runtime["component"]["entry_count"], 28)
        self.assertEqual(runtime["iso_build"]["member_count"], 66)
        self.assertEqual(
            runtime["iso_build"]["unchanged_member_count"],
            63,
        )
        self.assertEqual(
            runtime["iso_build"]["pcsx2_v263_image_type"],
            "DVD",
        )
        self.assertTrue(all(runtime["static_acceptance"].values()))
        self.assertEqual(runtime["runtime"]["status"], "not_tested")
        self.assertEqual(
            runtime["runtime"]["required_iso_sha256"],
            runtime["iso_build"]["output"]["sha256"],
        )
        self.assertIn(
            "world_history_scroll_final_segment_visible",
            runtime["runtime"]["pending_gates"],
        )


if __name__ == "__main__":
    unittest.main()
