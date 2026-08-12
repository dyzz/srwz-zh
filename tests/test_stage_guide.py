import hashlib
import json
import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GUIDE = PROJECT_ROOT / "guide/srwz-z-flow-guide.html"
MANIFEST = PROJECT_ROOT / "guide/stage-guide-manifest.json"
HIDDEN = PROJECT_ROOT / "guide/data/hidden-elements.json"
PROGRESSION = PROJECT_ROOT / "guide/data/progression.json"


class StageGuideTests(unittest.TestCase):
    def test_stage_guide_coverage_and_evidence_contract(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        coverage = manifest["coverage"]
        self.assertEqual(coverage["playable_title_count"], 107)
        self.assertEqual(coverage["playable_resource_number_count"], 107)
        self.assertEqual(coverage["playable_chunk_count"], 153)
        self.assertEqual(coverage["flow_condition_count"], 546)
        self.assertEqual(coverage["all_parsed_condition_count"], 558)
        self.assertEqual(coverage["condition_corpus_count"], 558)
        self.assertEqual(coverage["hidden_entry_count"], 36)
        self.assertEqual(coverage["hidden_step_count"], 160)
        self.assertEqual(coverage["progression_entry_count"], 81)
        self.assertEqual(coverage["progression_stage_card_count"], 87)
        self.assertEqual(coverage["akurasu_correction_count"], 9)
        self.assertEqual(coverage["akurasu_correction_card_count"], 11)
        self.assertEqual(sum(coverage["evidence_level_counts"].values()), 160)
        self.assertGreaterEqual(coverage["used_global_term_count"], 200)

    def test_every_playable_resource_has_a_locked_stage_witness(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(
            set(manifest["resources"]),
            {f"{number:03d}" for number in range(1, 108)},
        )
        for number, chunks in manifest["resources"].items():
            self.assertTrue(chunks)
            for chunk in chunks:
                self.assertRegex(chunk["resource_name"], rf"^stg_{number}[a-z]?\.bin$")
                self.assertRegex(chunk["function_address"], r"^0x[0-9A-F]{8}$")
                self.assertRegex(chunk["stored_sha256"], r"^[0-9a-f]{64}$")
                self.assertRegex(chunk["decoded_sha256"], r"^[0-9a-f]{64}$")

    def test_guide_entries_are_rendered_and_globally_term_bound(self):
        source = json.loads(HIDDEN.read_text(encoding="utf-8"))
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        page = GUIDE.read_text(encoding="utf-8")
        ids = [entry["id"] for entry in source["entries"]]
        self.assertEqual(len(ids), 36)
        self.assertEqual(len(set(ids)), 36)
        for entry_id in ids:
            self.assertIn(f'id="secret-{entry_id}"', page)
        placeholders = set()
        for source_path in (HIDDEN, PROGRESSION):
            placeholders.update(
                re.findall(
                    r"\{\{([^{}]+)\}\}",
                    source_path.read_text(encoding="utf-8"),
                )
            )
        self.assertEqual(placeholders, set(manifest["terminology"]["used_ids"]))
        self.assertEqual(set(manifest["terminology"]["sources"]), placeholders)

    def test_player_ui_is_two_views_and_has_no_collapsed_content(self):
        page = GUIDE.read_text(encoding="utf-8")
        self.assertEqual(page.count('<a class="mode-tab'), 2)
        self.assertEqual(page.count('class="guide-panel"'), 2)
        self.assertNotIn("<details", page)
        self.assertNotIn("<summary", page)
        self.assertNotIn('class="hero', page)
        self.assertNotIn('class="toolbar', page)
        self.assertNotIn('type="search"', page)
        self.assertNotIn("证据定位", page)
        self.assertNotIn("全局术语绑定", page)
        self.assertIn("加入／取得", page)
        self.assertIn("强化／新能力", page)
        self.assertIn("本话隐藏进度", page)
        self.assertEqual(page.count('class="stage-block correction"'), 11)

    def test_single_file_page_has_no_runtime_network_dependency(self):
        page = GUIDE.read_text(encoding="utf-8")
        self.assertTrue(page.startswith("<!doctype html>"))
        self.assertIn('<script type="application/json" id="guide-manifest">', page)
        self.assertIsNone(
            re.search(r"<(?:script|img)[^>]+src=[\"']https?://", page, re.I)
        )
        self.assertIsNone(re.search(r"<link[^>]+href=[\"']https?://", page, re.I))
        self.assertNotIn("@import", page)
        self.assertNotIn("fetch(", page)
        for ordinal in range(107):
            self.assertIn(f'id="stage-{ordinal:03d}"', page)

    def test_manifest_input_hashes_are_current(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        for relative, lock in manifest["inputs"].items():
            payload = (PROJECT_ROOT / relative).read_bytes()
            self.assertEqual(len(payload), lock["size"])
            self.assertEqual(hashlib.sha256(payload).hexdigest(), lock["sha256"])


if __name__ == "__main__":
    unittest.main()
