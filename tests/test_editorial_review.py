from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools/build_editorial_review.py"
SPEC = importlib.util.spec_from_file_location("build_editorial_review", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class EditorialReviewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.glossary = MODULE.load_global_glossary(MODULE.GLOSSARY_DIR)
        cls.glossary_by_id = MODULE.global_glossary_by_id(cls.glossary)

    def test_stage0_candidates_match_source_and_cover_all_targets(self) -> None:
        rows, stats = MODULE.build_stage_rows()
        self.assertEqual(stats, {"total": 296, "changed": 64, "risk": 5})
        self.assertEqual(len({row["id"] for row in rows}), 296)

        by_short_id = {row["short_id"]: row for row in rows}
        self.assertEqual(
            by_short_id["023FA0"]["candidate_translation"],
            "“再多加点热血成分，\n　不也挺好吗？”",
        )
        self.assertNotEqual(
            by_short_id["023FA0"]["candidate_translation"],
            by_short_id["023FA0"]["current_translation"],
        )
        self.assertEqual(by_short_id["022140"]["risks"], ["glyph_writeback_check"])

    def test_library_uses_only_fixed_snapshot_and_candidate_rules(self) -> None:
        rows, stats = MODULE.build_library_rows()
        self.assertEqual(
            stats,
            {"total": 2709, "changed": 468, "risk": 49, "human_reviewed": 22},
        )
        self.assertEqual(len({row["id"] for row in rows}), 2709)
        self.assertTrue(all("machine_draft" in row["source_status"] for row in rows))
        self.assertTrue(any("ZAFT" in row["candidate_translation"] for row in rows))
        self.assertFalse(any("扎夫特" in row["candidate_translation"] for row in rows))
        deprecated_terms = sorted(
            {
                variant
                for term in self.glossary
                if term["variant_scope"] == "global"
                for variant in term["deprecated_translations"]
            }
        )
        self.assertFalse(
            any(term in row["candidate_translation"] for row in rows for term in deprecated_terms)
        )

        by_id = {row["id"]: row for row in rows}
        self.assertIn("雷本·盖涅拉尔", by_id["library-text/03dcd20412db5d2e"]["candidate_translation"])
        self.assertIn("雷本充沛的斗志", by_id["library-text/03dcd20412db5d2e"]["candidate_translation"])
        self.assertIn("艾岱尔", by_id["library-text/1328aeae2cc71d3d"]["candidate_translation"])
        self.assertIn("休兰", by_id["library-text/1328aeae2cc71d3d"]["candidate_translation"])
        self.assertEqual(
            by_id["library-text/0004617f45ab7a01"]["candidate_translation"],
            "奈基克 雅典娜机",
        )
        self.assertNotIn(
            "glossary_hint_mismatch",
            by_id["library-text/0004617f45ab7a01"]["risks"],
        )
        scub = by_id["library-text/3006da848ec398e1"]
        self.assertEqual(scub["review_origin"], "codex_human_review")
        self.assertIn("斯卡布珊瑚", scub["candidate_translation"])
        self.assertEqual(scub["risks"], [])
        self.assertEqual(scub["accepted_audit_risks"], [])

        side_three = by_id["library-text/5293c233c5d0d1c3"]
        self.assertIn("宇宙殖民地群", side_three["candidate_translation"])
        self.assertIn("康提主义", side_three["candidate_translation"])
        self.assertNotIn(
            "people/speaker-e09d95738b2d",
            {term["id"] for term in side_three["glossary_terms"]},
        )
        contolism_rows = [
            row
            for row in rows
            if "コントリズム" in row["source_text"].replace("\n", "")
        ]
        self.assertEqual(len(contolism_rows), 4)
        self.assertTrue(
            all("康提主义" in row["candidate_translation"] for row in contolism_rows)
        )
        self.assertTrue(
            all(
                "Contrismo" not in row["candidate_translation"]
                and "Contolism" not in row["candidate_translation"]
                for row in contolism_rows
            )
        )
        contolism_definition = by_id["library-text/31b1cf6d90e70522"]
        self.assertIn("地球圣地主义", contolism_definition["candidate_translation"])
        self.assertIn("Side国家主义", contolism_definition["candidate_translation"])
        self.assertNotIn("Erathism", contolism_definition["candidate_translation"])
        self.assertNotIn("Sidism", contolism_definition["candidate_translation"])
        self.assertEqual(contolism_definition["risks"], [])
        self.assertTrue(
            all(
                not row["risks"]
                for row in rows
                if row["review_origin"] == "codex_human_review"
            )
        )
        self.assertEqual(
            by_id["library-text/09ea11c376478075"]["candidate_translation"],
            "太阳亚库艾里翁",
        )
        self.assertEqual(
            by_id["library-text/9a1294c66f8ba95e"]["candidate_translation"],
            "梅迪克·赫尔特",
        )
        self.assertEqual(
            by_id["library-text/aeac9828182c51d5"]["candidate_translation"],
            "梅迪克",
        )
        self.assertEqual(
            by_id["library-text/7109cec402fcc027"]["candidate_translation"],
            "贝加之王",
        )
        self.assertFalse(
            any("translation_collision" in row["risks"] for row in rows)
        )

    def test_risk_filter_keeps_only_unchanged_japanese_kana(self) -> None:
        config = MODULE.load_json(MODULE.LIBRARY_POLISH)
        common = {
            "candidate": "18.6m",
            "kind": "name_or_metadata",
            "config": config,
            "glossary_by_id": {},
            "relevant_term_ids": set(),
        }
        self.assertEqual(
            MODULE.filter_library_risk_details(
                [{"code": "unchanged_source"}],
                source_text="１８．６ｍ",
                source_match_text="１８．６ｍ",
                **common,
            ),
            [],
        )
        self.assertEqual(
            MODULE.filter_library_risk_details(
                [{"code": "unchanged_source"}],
                source_text="テスト",
                source_match_text="テスト",
                **{**common, "candidate": "テスト"},
            ),
            [{"code": "unchanged_source"}],
        )

    def test_risk_filter_only_enforces_approved_global_terms(self) -> None:
        config = MODULE.load_json(MODULE.LIBRARY_POLISH)
        detail = {
            "code": "glossary_hint_mismatch",
            "terms": [
                {"id": "term/proposed", "target": "提议词"},
                {"id": "term/approved", "target": "正式词"},
            ],
        }
        filtered = MODULE.filter_library_risk_details(
            [detail],
            source_text="原文",
            source_match_text="原文",
            candidate="另一种译法",
            kind="body",
            config=config,
            glossary_by_id={
                "term/proposed": {
                    "translation": "提议词",
                    "status": "proposed",
                    "enforce": False,
                },
                "term/approved": {
                    "translation": "正式词",
                    "status": "approved",
                    "enforce": True,
                },
            },
            relevant_term_ids={"term/proposed", "term/approved"},
        )
        self.assertEqual(len(filtered), 1)
        self.assertEqual(
            [term["id"] for term in filtered[0]["terms"]],
            ["term/approved"],
        )

    def test_ascii_risk_requires_source_or_bound_glossary_provenance(self) -> None:
        config = MODULE.load_json(MODULE.LIBRARY_POLISH)
        details = [{"code": "ascii_word", "values": ["GAT-X", "ZAFT", "invented"]}]
        filtered = MODULE.filter_library_risk_details(
            details,
            source_text="ＧＡＴ－Ｘとザフト",
            source_match_text="ＧＡＴ－Ｘとザフト",
            candidate="GAT-X、ZAFT、invented",
            kind="body",
            config=config,
            glossary_by_id={
                "organization/zaft": {
                    "translation": "ZAFT",
                    "status": "approved",
                    "enforce": True,
                }
            },
            relevant_term_ids={"organization/zaft"},
        )
        self.assertEqual(
            filtered,
            [{"code": "ascii_word", "values": ["invented"]}],
        )

    def test_candidate_collisions_are_recomputed_after_editorial_changes(self) -> None:
        rows = [
            {
                "source_text": "機動戦士　ガンダム",
                "candidate_translation": "机动战士高达",
                "risks": [],
                "risk_details": [],
            },
            {
                "source_text": "機動戦士 ガンダム",
                "candidate_translation": "机动战士高达",
                "risks": [],
                "risk_details": [],
            },
            {
                "source_text": "甲",
                "candidate_translation": "同名",
                "risks": [],
                "risk_details": [],
            },
            {
                "source_text": "乙",
                "candidate_translation": "同名",
                "risks": [],
                "risk_details": [],
            },
        ]
        MODULE.add_library_collision_risks(rows)
        self.assertEqual(rows[0]["risks"], [])
        self.assertEqual(rows[1]["risks"], [])
        self.assertEqual(rows[2]["risks"], ["translation_collision"])
        self.assertEqual(rows[3]["risks"], ["translation_collision"])

    def test_declared_collision_exception_is_exact_and_fail_closed(self) -> None:
        rows = [
            {
                "id": "library-text/a",
                "source_text": "隼人",
                "candidate_translation": "隼人",
                "risks": [],
                "risk_details": [],
            },
            {
                "id": "library-text/b",
                "source_text": "ハヤト",
                "candidate_translation": "隼人",
                "risks": [],
                "risk_details": [],
            },
        ]
        accepted = [
            {
                "translation": "隼人",
                "ids": ["library-text/a", "library-text/b"],
                "reason": "不同人物共用通行中文短名。",
            }
        ]
        MODULE.add_library_collision_risks(rows, accepted)
        self.assertTrue(all(not row["risks"] for row in rows))

        with self.assertRaisesRegex(ValueError, "stale accepted"):
            MODULE.add_library_collision_risks(
                rows,
                [
                    {
                        "translation": "隼人",
                        "ids": ["library-text/a", "library-text/missing"],
                        "reason": "错误声明。",
                    }
                ],
            )

    def test_library_style_rules_are_deterministic(self) -> None:
        config = MODULE.load_json(MODULE.LIBRARY_POLISH)
        self.assertNotIn("glossary_decisions", config)
        self.assertNotIn("scoped_replacements", config)
        self.assertNotIn("term_conflicts", config)
        result, applied = MODULE.apply_library_rules(
            '扎夫特的plant称作“PLANT”，也写作"plant"。',
            config,
            [self.glossary_by_id["organization/zaft"]],
        )
        self.assertEqual(result, "ZAFT的PLANT称作“PLANT”，也写作“PLANT”。")
        self.assertIn("扎夫特→ZAFT[organization/zaft]", applied)
        self.assertIn("ASCII双引号→中文双引号", applied)
        self.assertIn("PLANT大小写", applied)

    def test_library_scoped_name_rules_do_not_damage_real_collisions(self) -> None:
        config = MODULE.load_json(MODULE.LIBRARY_POLISH)
        untouched, _ = MODULE.apply_library_rules("夏亚与雷文会面。", config)
        self.assertEqual(untouched, "夏亚与雷文会面。")

        shaya, _ = MODULE.apply_library_rules(
            "夏亚抵达。",
            config,
            [self.glossary_by_id["people/speaker-7e722f885dfc"]],
        )
        self.assertEqual(shaya, "夏伊亚抵达。")
        leben, _ = MODULE.apply_library_rules(
            "雷文大尉出击。",
            config,
            [self.glossary_by_id["people/leben"]],
        )
        self.assertEqual(leben, "雷本大尉出击。")

    def test_term_conflicts_only_match_deprecated_variants(self) -> None:
        term = self.glossary_by_id["unit/naikick"]
        self.assertEqual(MODULE.find_term_conflicts("奈基克", [term]), [])
        conflicts = MODULE.find_term_conflicts("纳伊基克", [term])
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["canonical"], "奈基克")

    def test_build_is_self_contained_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_dir = Path(first)
            second_dir = Path(second)
            first_manifest = MODULE.build(first_dir)
            second_manifest = MODULE.build(second_dir)

            self.assertEqual(first_manifest["dataset_id"], second_manifest["dataset_id"])
            self.assertEqual((first_dir / "candidate.json").read_bytes(), (second_dir / "candidate.json").read_bytes())
            self.assertEqual((first_dir / "index.html").read_bytes(), (second_dir / "index.html").read_bytes())

            html = (first_dir / "index.html").read_text(encoding="utf-8")
            self.assertNotIn(MODULE.DATA_MARKER, html)
            self.assertNotIn("data.js", html)
            self.assertNotIn("http://", html)
            self.assertNotIn("https://", html)
            self.assertIn('id="review-data"', html)
            self.assertIn("Codex 已逐条审核", html)

            candidate = json.loads((first_dir / "candidate.json").read_text(encoding="utf-8"))
            self.assertFalse(candidate["promotion_allowed"])
            self.assertEqual(candidate["summary"]["total"], 3005)


if __name__ == "__main__":
    unittest.main()
