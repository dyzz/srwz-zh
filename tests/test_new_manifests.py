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


if __name__ == "__main__":
    unittest.main()
