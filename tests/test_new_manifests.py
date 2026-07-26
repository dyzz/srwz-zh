import hashlib
import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = PROJECT_ROOT / "manifests"


def load(name):
    return json.loads((MANIFESTS / name).read_text(encoding="utf-8"))


class NewManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = load("original-disc.json")
        cls.encoder = load("codec-encoder-validation.json")
        cls.font = load("font-analysis.json")
        cls.corpus = load("corpus-export.json")
        cls.rebuild = load("archive-rebuild-validation.json")
        cls.assets = load("asset-inventory.json")
        cls.map_names = load("map-name-parse.json")
        cls.tim2_writeback = load("tim2-writeback-noop.json")
        cls.image_canary = load("image-canary-validation.json")
        cls.title_menu_zh = load("title-menu-zh-validation.json")

    def test_encoder_all_tested_streams_round_trip(self):
        totals = self.encoder["totals"]
        self.assertEqual(totals["failure_count"], 0)
        self.assertEqual(
            totals["tested_stream_count"],
            totals["round_trip_exact_count"],
        )
        self.assertEqual(
            totals["tested_stream_count"],
            totals["flags_match_original_count"],
        )
        self.assertEqual(
            totals["tested_stream_count"],
            totals["game_runtime_grammar_compatible_count"],
        )
        self.assertEqual(totals["zero_literal_block_count"], 0)
        self.assertEqual(
            totals["nonfinal_zero_match_block_count"],
            0,
        )

    def test_encoder_sources_match_original_manifest(self):
        expected = {
            value["path"]: value["sha256"]
            for value in self.original["key_files"]
            if value["path"] in self.encoder["sources"]
        }
        self.assertEqual(self.encoder["sources"], expected)

    def test_font_patch_is_confined_to_declared_region(self):
        patch = self.font["patch_analysis"]
        self.assertEqual(patch["changed_bytes_outside_region"], 0)
        self.assertEqual(
            patch["region_size"],
            patch["block_size"] * patch["block_count"],
        )
        self.assertEqual(patch["glyph_contract"]["glyph_size"], 288)
        self.assertEqual(patch["glyph_contract"]["glyph_count"], 4480)

    def test_font_code_mapping_has_verified_glyph_coverage(self):
        mapping = self.font["glyph_mapping"]
        self.assertEqual(
            mapping["supported_text_code_count"],
            (
                mapping["standard_text_code_count"]
                + mapping["supported_extended_text_code_count"]
            ),
        )
        self.assertEqual(
            mapping["supported_text_code_count"]
            + mapping["unsupported_text_code_count"],
            self.font["codebook_inventory"]["mapped_code_count"],
        )
        self.assertEqual(
            mapping["referenced_glyph_count"]
            + mapping["glyphs_not_referenced_by_text_table_count"],
            self.font["patch_analysis"]["glyph_contract"]["glyph_count"],
        )
        self.assertEqual(
            mapping["standard_extended_glyph_overlap_count"],
            0,
        )

    def test_real_archives_rebuild_and_round_trip(self):
        stage = self.rebuild["stage"]
        self.assertEqual(stage["chunk_count"], 205)
        self.assertEqual(
            stage["decoded_round_trip_exact_count"],
            stage["chunk_count"],
        )
        self.assertTrue(stage["offsets_aligned_16"])
        self.assertTrue(stage["stage_offset_source_available"])
        self.assertTrue(stage["hb_offset_reread_exact"])

        mtv = self.rebuild["mtv_pros"]
        self.assertEqual(mtv["chunk_count"], 14)
        self.assertEqual(
            mtv["decoded_round_trip_exact_count"],
            mtv["chunk_count"],
        )
        self.assertEqual(mtv["summary_identity_exact_chunk_count"], 14)
        self.assertTrue(mtv["slps_offset_reread_exact"])

    def test_corpus_counts_match_parser_manifest(self):
        parsed = load("iso-data-parse.json")["parsed"]
        self.assertEqual(
            self.corpus["text_round_trip_exact_count"],
            self.corpus["entry_count"],
        )
        self.assertEqual(
            self.corpus["entry_count"],
            parsed["stable_id_count"],
        )
        self.assertEqual(
            self.corpus["domain_counts"],
            {
                domain: parsed[domain]["entry_count"]
                for domain in ("menu", "story", "summary")
            },
        )

    def test_asset_inventory_counts_only_validated_tim2_records(self):
        totals = self.assets["totals"]
        self.assertEqual(totals["tim2_record_count"], 706)
        self.assertEqual(totals["picture_count"], 1146)
        self.assertEqual(totals["raw_tim2_magic_count"], 712)
        self.assertLessEqual(
            totals["tim2_record_count"],
            totals["raw_tim2_magic_count"],
        )
        self.assertEqual(
            self.assets["reference_kvm_comparison"]["changed_chunk_indices"],
            [5, 6],
        )
        self.assertEqual(
            totals["tim2_record_count"],
            (
                sum(
                    item["tim2_record_count"]
                    for item in self.assets["archives"]
                )
                + sum(
                    item["tim2_record_count"]
                    for item in self.assets["direct_members"]
                )
            ),
        )
        config_path = (
            PROJECT_ROOT / "config" / "assets" / "archive-inventory.json"
        )
        self.assertEqual(
            self.assets["config_sha256"],
            hashlib.sha256(config_path.read_bytes()).hexdigest(),
        )

    def test_map_names_have_strict_fixed_record_coverage(self):
        self.assertEqual(self.map_names["record_size"], 256)
        self.assertEqual(self.map_names["record_count"], 195)
        self.assertEqual(
            self.map_names["stable_id_count"],
            self.map_names["record_count"],
        )
        self.assertLess(self.map_names["max_encoded_size"], 256)

    def test_tim2_noop_preserves_real_kvm_archive(self):
        report = self.tim2_writeback
        self.assertEqual(report["runtime_acceptance"], "not tested")
        self.assertEqual(report["source"]["member"], "KURODATA/KVMDATA.BIN")
        self.assertEqual(report["source"]["chunk_index"], 5)
        self.assertEqual(report["source"]["source_kind"], "original_iso_member")
        self.assertEqual(
            report["config_sha256"],
            hashlib.sha256(
                (
                    PROJECT_ROOT
                    / "config"
                    / "assets"
                    / "archive-inventory.json"
                ).read_bytes()
            ).hexdigest(),
        )
        injection = report["injection"]
        self.assertEqual(injection["changed_pixel_count"], 0)
        self.assertEqual(injection["changed_image_byte_count"], 0)
        self.assertTrue(injection["visual_rgba_exact"])
        self.assertTrue(injection["chunk_size_unchanged"])
        self.assertTrue(injection["non_target_archive_bytes_exact"])
        output = report["output"]
        self.assertTrue(output["archive_byte_identical"])
        self.assertTrue(output["chunk_byte_identical"])
        self.assertEqual(
            output["member_sha256"],
            report["source"]["member_sha256"],
        )
        self.assertEqual(
            output["chunk_sha256"],
            report["source"]["chunk_sha256"],
        )

    def test_image_canary_has_static_and_runtime_acceptance(self):
        report = self.image_canary
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["runtime_acceptance"], "passed")
        self.assertEqual(
            report["source_ownership"]["source_member"],
            "DATA/VT1.BIN",
        )
        self.assertEqual(
            report["source_ownership"]["chunk_index"],
            6,
        )
        self.assertEqual(
            report["source_ownership"]["record_index"],
            1,
        )
        injection = report["component_build"]["injection"]
        self.assertEqual(injection["changed_index_byte_count"], 351)
        self.assertEqual(injection["changed_pixel_count"], 351)
        self.assertTrue(injection["tim2_metadata_preserved"])
        self.assertTrue(injection["clut_preserved"])
        self.assertTrue(
            report["component_build"]["codec"][
                "decoded_round_trip_exact"
            ]
        )
        self.assertEqual(
            report["iso_build"]["unchanged_member_count"],
            64,
        )
        self.assertTrue(report["iso_build"]["byte_reproducible"])
        runtime = report["runtime"]
        self.assertEqual(runtime["disc"]["image_type"], "DVD")
        self.assertEqual(runtime["disc"]["tlb_miss_count"], 0)
        texture = runtime["texture_dump_run"]
        self.assertEqual(texture["changed_pixel_count"], 351)
        self.assertEqual(texture["unexpected_substitution_count"], 0)
        self.assertTrue(texture["expected_rgba_substitution_exact"])
        self.assertEqual(
            texture["original_color_counts"]["FFFF1F80"],
            351,
        )
        self.assertEqual(
            texture["canary_color_counts"]["FFFF1F80"],
            0,
        )
        self.assertEqual(
            texture["canary_color_counts"]["64646480"],
            (
                texture["original_color_counts"]["64646480"]
                + texture["changed_pixel_count"]
            ),
        )
        self.assertTrue(
            runtime["external_state_restore"][
                "pcsx2_config_restored_byte_identical"
            ]
        )

    def test_title_menu_chinese_has_exact_runtime_texture_acceptance(self):
        report = self.title_menu_zh
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["runtime_acceptance"], "passed")
        self.assertEqual(
            [
                (item["source"], item["target"])
                for item in report["translations"]
            ],
            [
                ("START", "开始"),
                ("LOAD", "读取"),
                ("CONTINUE", "继续"),
                ("LIBRARY", "资料库"),
            ],
        )
        self.assertEqual(
            report["component_build"]["config"]["sha256"],
            hashlib.sha256(
                (
                    PROJECT_ROOT
                    / "config"
                    / "canary"
                    / "tim2-vt1-title-zh.json"
                ).read_bytes()
            ).hexdigest(),
        )
        self.assertEqual(
            report["iso_build"]["config"]["sha256"],
            hashlib.sha256(
                (
                    PROJECT_ROOT
                    / "config"
                    / "iso"
                    / "title-menu-zh-build.json"
                ).read_bytes()
            ).hexdigest(),
        )
        injection = report["component_build"]["injection"]
        self.assertEqual(injection["changed_pixel_count"], 12514)
        self.assertEqual(
            injection["changed_image_byte_count"],
            injection["changed_pixel_count"],
        )
        self.assertTrue(injection["psmt8_round_trip_exact"])
        self.assertTrue(injection["tim2_metadata_preserved"])
        self.assertTrue(injection["clut_preserved"])
        self.assertEqual(
            report["iso_build"]["unchanged_member_count"],
            64,
        )
        runtime = report["runtime"]
        self.assertEqual(runtime["disc"]["image_type"], "DVD")
        self.assertEqual(runtime["disc"]["tlb_miss_count"], 0)
        self.assertTrue(
            runtime["visual_run"]["all_labels_visible"]
        )
        self.assertFalse(
            runtime["visual_run"]["clipping_or_overlap_observed"]
        )
        texture = runtime["texture_dump"]
        self.assertEqual(
            texture["rgba_sha256"],
            texture["offline_preview_rgba_sha256"],
        )
        self.assertTrue(texture["offline_runtime_rgba_exact"])
        self.assertTrue(
            runtime["external_state_restore"][
                "pcsx2_config_restored_byte_identical"
            ]
        )


if __name__ == "__main__":
    unittest.main()
