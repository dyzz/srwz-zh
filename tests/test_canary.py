import json
import tempfile
import unittest
from pathlib import Path

from tools.srwz.canary import (
    CanaryError,
    double_byte_width_class,
    normalized_cjk_bbox_size,
    quantize_gray_4bpp,
    rasterizer_point_size,
    rebuild_archive_with_replacement,
    verify_reserved_codes_absent,
)
from tools.srwz.corpus import text_sha256
from tools.srwz.font import standard_glyph_index
from tools.srwz.project import (
    load_build_profile,
    validate_profile_encoding,
)
from tools.srwz.text import (
    TextTable,
    decode_text,
    encode_text,
    load_text_table,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class CanaryTests(unittest.TestCase):
    def test_rasterizer_point_size_is_uniform_for_every_character(self):
        rasterizer = {"point_size": 22}
        self.assertEqual(rasterizer_point_size("研", rasterizer), 22)
        self.assertEqual(rasterizer_point_size("班", rasterizer), 22)

    def test_rasterizer_point_size_rejects_every_character_correction(self):
        with self.assertRaisesRegex(
            CanaryError,
            "per-character optical corrections are forbidden",
        ):
            rasterizer_point_size(
                "班",
                {
                    "point_size": 22,
                    "optical_corrections": {
                        "班": {
                            "point_size": 22.1,
                            "reason": "Forbidden special case.",
                        },
                    },
                },
            )

    def test_gray_quantization_is_bounded_and_deterministic(self):
        values = bytes((0, 8, 9, 127, 128, 246, 247, 255))
        self.assertEqual(
            quantize_gray_4bpp(values),
            bytes((0, 0, 1, 7, 8, 14, 15, 15)),
        )

    def test_uniform_cjk_bbox_normalization_uses_geometry_not_characters(self):
        policy = {
            "target_bbox_size": 22,
        }
        self.assertEqual(normalized_cjk_bbox_size(41, 43, policy), (21, 22))
        self.assertEqual(normalized_cjk_bbox_size(45, 43, policy), (22, 21))
        self.assertEqual(normalized_cjk_bbox_size(34, 35, policy), (21, 22))
        self.assertEqual(normalized_cjk_bbox_size(42, 5, policy), (22, 3))
        self.assertEqual(normalized_cjk_bbox_size(6, 42, policy), (3, 22))

    def test_selected_codes_preserve_default_width_class(self):
        self.assertEqual(
            double_byte_width_class(0x967B),
            "default_double_byte",
        )
        self.assertEqual(
            double_byte_width_class(0x95D2),
            "default_double_byte",
        )
        self.assertEqual(
            double_byte_width_class(0x987E),
            "default_double_byte",
        )
        self.assertEqual(
            double_byte_width_class(0x987F),
            "default_double_byte",
        )

    def test_replaces_one_aligned_archive_chunk_only(self):
        source = b"A" * 16 + b"B" * 16 + b"C" * 16
        rebuilt, offsets, padding = rebuild_archive_with_replacement(
            source,
            (0, 16, 32, 48),
            chunk_index=1,
            encoded_replacement=b"X" * 17,
        )
        self.assertEqual(offsets, (0, 16, 48, 64))
        self.assertEqual(padding, 15)
        self.assertEqual(rebuilt[:16], b"A" * 16)
        self.assertEqual(rebuilt[16:33], b"X" * 17)
        self.assertEqual(rebuilt[33:48], bytes(15))
        self.assertEqual(rebuilt[48:], b"C" * 16)

    def test_archive_replacement_rejects_unaligned_source(self):
        with self.assertRaisesRegex(CanaryError, "not aligned"):
            rebuild_archive_with_replacement(
                b"A" * 17,
                (0, 1, 17),
                chunk_index=0,
                encoded_replacement=b"X",
            )

    def test_archive_replacement_can_preserve_a_larger_allocation(self):
        source = b"A" * 16 + b"B" * 16
        rebuilt, offsets, padding = rebuild_archive_with_replacement(
            source,
            (0, 16, 32),
            chunk_index=0,
            encoded_replacement=b"X" * 3,
            minimum_allocation=16,
        )
        self.assertEqual(offsets, (0, 16, 32))
        self.assertEqual(padding, 13)
        self.assertEqual(rebuilt[:3], b"XXX")
        self.assertEqual(rebuilt[3:16], bytes(13))
        self.assertEqual(rebuilt[16:], b"B" * 16)

    def test_reserved_code_scan_observes_token_boundaries(self):
        table = TextTable(
            characters={0x8198: "A"},
            tags={},
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corpus.jsonl"
            path.write_text(
                json.dumps({"source_text": "A~"}) + "\n",
                encoding="utf-8",
            )
            self.assertEqual(
                verify_reserved_codes_absent(
                    path,
                    table,
                    (0x987E,),
                    expected_entry_count=1,
                ),
                1,
            )

    def test_reserved_code_scan_rejects_real_token(self):
        table = TextTable(
            characters={0x987E: "測"},
            tags={},
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corpus.jsonl"
            path.write_text(
                json.dumps({"source_text": "測"}) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(CanaryError, "987E"):
                verify_reserved_codes_absent(
                    path,
                    table,
                    (0x987E,),
                    expected_entry_count=1,
                )

    def test_repository_canary_has_no_hook_and_exact_text_size(self):
        config = json.loads(
            (
                PROJECT_ROOT
                / "config"
                / "canary"
                / "minimal-slps-font.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            config["renderer_contract"]["runtime_hooks"],
            [],
        )
        self.assertFalse(
            config["renderer_contract"]["code_injection"]
        )
        self.assertEqual(
            len(config["renderer_contract"]["instruction_windows"]),
            5,
        )
        candidate_range = config["font_segment"][
            "static_blank_candidate_range"
        ]
        candidate_codes = tuple(
            range(
                int(candidate_range["code_start"], 0),
                int(candidate_range["code_end_inclusive"], 0) + 1,
            )
        )
        self.assertEqual(len(candidate_codes), 13)
        self.assertEqual(
            [standard_glyph_index(code) for code in candidate_codes],
            list(range(4467, 4480)),
        )
        self.assertNotIn("glyphs", config)
        self.assertNotIn("text_patch", config)
        selection = load_build_profile(
            PROJECT_ROOT,
            PROJECT_ROOT / config["profile"],
        )
        surface = selection.single_surface()
        decision = selection.translation_for(surface.entry_id)
        glyphs = [
            assignment.to_glyph_lock()
            for assignment in selection.assignments
        ]
        self.assertEqual(
            [
                standard_glyph_index(int(glyph["code"], 16))
                for glyph in glyphs
            ],
            [glyph["glyph_index"] for glyph in glyphs],
        )
        table = load_text_table(
            PROJECT_ROOT
            / "vendor"
            / "upstream-python"
            / "project"
            / "tbl_all.json"
        )
        overrides = {
            glyph["character"]: int(glyph["code"], 16)
            for glyph in glyphs
        }
        source = bytes.fromhex(
            "8351815B8380967B95D282F08376838C834382B582DC82B7814200"
        )
        decoded_source = decode_text(source, 0, table)
        self.assertEqual(
            text_sha256(decoded_source.text),
            surface.source_text_sha256,
        )
        replacement = encode_text(
            decision.translation,
            table,
            overrides=overrides,
            terminate=True,
        )
        self.assertEqual(
            source,
            bytes.fromhex(
                "8351815B8380967B95D282F08376838C834382B582DC82B7814200"
            ),
        )
        self.assertEqual(
            replacement,
            bytes.fromhex(
                "8351815B8380987E987F82F08376838C834382B582DC82B7814200"
            ),
        )
        self.assertEqual(len(source), len(replacement))

    def test_current_canary_matches_output_lock_and_runtime_manifest_is_historical(self):
        config = json.loads(
            (
                PROJECT_ROOT
                / "config"
                / "canary"
                / "minimal-slps-font.json"
            ).read_text(encoding="utf-8")
        )
        manifest = json.loads(
            (
                PROJECT_ROOT
                / "manifests"
                / "static-canary-validation.json"
            ).read_text(encoding="utf-8")
        )
        current = json.loads(
            (
                PROJECT_ROOT
                / "work/build/canary-menu/components/component-validation.json"
            ).read_text(encoding="utf-8")
        )
        expected = config["expected_outputs"]
        selection = load_build_profile(
            PROJECT_ROOT,
            PROJECT_ROOT / config["profile"],
        )
        self.assertEqual(
            manifest["production_inputs"],
            selection.to_metadata(),
        )
        table = load_text_table(
            PROJECT_ROOT
            / "vendor"
            / "upstream-python"
            / "project"
            / "tbl_all.json"
        )
        self.assertEqual(
            manifest["profile_validation"],
            validate_profile_encoding(selection, table),
        )
        self.assertEqual(
            current["decoded_font"]["output_sha256"],
            expected["decoded_font_sha256"],
        )
        self.assertEqual(
            current["slps_output"]["sha256"],
            expected["slps"]["sha256"],
        )
        self.assertEqual(
            current["slps_output"]["diff"]["diff_count"],
            expected["slps"]["diff_count"],
        )
        self.assertEqual(
            current["vt1_output"]["sha256"],
            expected["vt1"]["sha256"],
        )
        self.assertEqual(
            current["vt1_output"]["replaced_encoded_sha256"],
            expected["encoded_font"]["sha256"],
        )
        self.assertEqual(
            current["preview_sha256"],
            expected["preview"]["sha256"],
        )
        self.assertEqual(current["runtime_acceptance"], "not tested")
        self.assertEqual(
            manifest["status"], "static_candidate_runtime_verified_separately"
        )
        self.assertNotEqual(
            manifest["decoded_font"]["output_sha256"],
            expected["decoded_font_sha256"],
        )
        self.assertEqual(
            manifest["slot_safety"]["static_blank_candidate_count"],
            config["font_segment"]["static_blank_candidate_range"][
                "count"
            ],
        )

    def test_global_font_flavor_uses_the_pinned_official_archive(self):
        lock = json.loads(
            (
                PROJECT_ROOT
                / "config"
                / "fonts"
                / "harmonyos-sans-sc.lock.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            lock["source_kind"],
            "pinned-official-archive",
        )
        self.assertEqual(lock["source_id"], "huawei-harmonyos-sans")
        self.assertTrue(lock["license"]["notice_required"])
        self.assertTrue(
            lock["archive"]["url"].startswith(
                "https://communityfile-drcn.op.dbankcloud.cn/"
            )
        )

    def test_runtime_manifest_proves_game_decoder_output(self):
        static = json.loads(
            (
                PROJECT_ROOT
                / "manifests"
                / "static-canary-validation.json"
            ).read_text(encoding="utf-8")
        )
        runtime = json.loads(
            (
                PROJECT_ROOT
                / "manifests"
                / "canary-iso-validation.json"
            ).read_text(encoding="utf-8")
        )
        runtime_inputs = dict(runtime["production_inputs"])
        self.assertTrue(
            runtime_inputs.pop("reconciled_after_profile_migration")
        )
        self.assertEqual(runtime_inputs, static["production_inputs"])
        decoder = runtime["runtime"]["game_decompressor"]
        self.assertTrue(decoder["full_decoded_font_exact"])
        self.assertEqual(runtime["runtime"]["tlb_miss_count"], 0)
        self.assertEqual(
            decoder["font_runtime_sha256"],
            static["decoded_font"]["output_sha256"],
        )
        self.assertEqual(
            runtime["runtime_acceptance"],
            "passed_full_game_decoder_output_hash_and_opening_visual_canary",
        )
        opening = runtime["runtime"]["opening_canary"]
        self.assertTrue(opening["runtime_bytes_exact"])
        self.assertTrue(opening["characters_visible"])
        self.assertFalse(opening["overlap_or_clipping_observed"])
        self.assertEqual(
            runtime["visual_menu_acceptance"],
            "passed_select_scenario_screenshot",
        )

    def test_e2_manifests_bind_all_three_isolated_iso_profiles(self):
        manifests = {
            profile_id: json.loads(
                (
                    PROJECT_ROOT
                    / "manifests"
                    / manifest_name
                ).read_text(encoding="utf-8")
            )
            for profile_id, manifest_name in (
                ("canary-menu", "canary-iso-validation.json"),
                ("canary-summary", "canary-summary-validation.json"),
                ("canary-story", "canary-story-validation.json"),
            )
        }
        for profile_id, manifest in manifests.items():
            config_name = (
                "canary-build.json"
                if profile_id == "canary-menu"
                else f"{profile_id}-build.json"
            )
            config = json.loads(
                (
                    PROJECT_ROOT / "config" / "iso" / config_name
                ).read_text(encoding="utf-8")
            )
            observed = (
                manifest["observed_output_iso"]
                if profile_id == "canary-menu"
                else manifest["iso_build"]
            )
            self.assertEqual(manifest["status"], "passed")
            self.assertEqual(
                observed["sha256"],
                config["output"]["expected_sha256"],
            )
            self.assertEqual(
                observed["size"],
                config["output"]["expected_size"],
            )
            self.assertEqual(
                manifest["runtime"]["tlb_miss_count"],
                0,
            )
            visual = (
                manifest["runtime"]["opening_canary"]
                if profile_id == "canary-menu"
                else manifest["runtime"]["visual"]
            )
            self.assertTrue(visual["characters_visible"])
            self.assertFalse(
                visual["overlap_or_clipping_observed"]
            )

    def test_complete_canary_manifest_binds_components_and_fixtures(self):
        component_config = json.loads(
            (
                PROJECT_ROOT
                / "config"
                / "canary"
                / "complete-content.json"
            ).read_text(encoding="utf-8")
        )
        iso_config = json.loads(
            (
                PROJECT_ROOT
                / "config"
                / "iso"
                / "canary-complete-build.json"
            ).read_text(encoding="utf-8")
        )
        manifest = json.loads(
            (
                PROJECT_ROOT
                / "manifests"
                / "canary-complete-validation.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["status"], "passed")
        self.assertEqual(
            manifest["iso_build"]["sha256"],
            iso_config["output"]["expected_sha256"],
        )
        self.assertEqual(
            manifest["iso_build"]["member_manifest_sha256"],
            iso_config["output"]["expected_member_manifest_sha256"],
        )
        self.assertEqual(
            set(manifest["independent_runtime_fixtures"]),
            {
                "canary-menu",
                "canary-summary",
                "canary-story",
            },
        )
        for profile_id, fixture in (
            manifest["independent_runtime_fixtures"].items()
        ):
            config_name = (
                "canary-build.json"
                if profile_id == "canary-menu"
                else f"{profile_id}-build.json"
            )
            fixture_config = json.loads(
                (
                    PROJECT_ROOT / "config" / "iso" / config_name
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(fixture["result"], "passed")
            self.assertEqual(
                fixture["candidate_iso_sha256"],
                fixture_config["output"]["expected_sha256"],
            )
        self.assertEqual(
            set(component_config["isolated_profiles"]),
            {"canary-summary", "canary-story"},
        )
        smoke = manifest["combined_runtime_smoke"]
        self.assertEqual(smoke["tlb_miss_count"], 0)
        self.assertTrue(smoke["decoded_font_exact"])
        self.assertTrue(
            smoke["pcsx2_config_restored_byte_identical"]
        )
        self.assertTrue(
            smoke["story_archive_load"]["opening_stage_loaded"]
        )


if __name__ == "__main__":
    unittest.main()
