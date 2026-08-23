import json
import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORPUS_PATH = PROJECT_ROOT / "corpus/zh/menu/system-ui-special-abilities.json"
GLOSSARY_ROOT = PROJECT_ROOT / "corpus/glossary"
PARTS_GLOSSARY_PATH = GLOSSARY_ROOT / "parts-v1.json"
REMAINING_UI_PATH = PROJECT_ROOT / "corpus/zh/menu/remaining-ui.json"
SEARCH_UI_PATH = PROJECT_ROOT / "corpus/zh/menu/system-ui-search.json"
BATTLE_PATH = PROJECT_ROOT / "corpus/zh/battle/srvc-lines.json"
CONTENT_PATH = (
    PROJECT_ROOT / "work/verification/zh-release-full-story-content.json"
)


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


class SpecialAbilityTranslationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = load(CORPUS_PATH)
        cls.entries = {
            int(row["id"].rsplit("/", 1)[1]): row
            for row in cls.corpus["entries"]
        }
        cls.glossary = {}
        for path in GLOSSARY_ROOT.glob("*.json"):
            for term in load(path).get("terms", []):
                cls.glossary.setdefault(term["id"], []).append(term)

    def test_complete_batch_is_reviewed_without_touching_structure_rows(self):
        self.assertEqual(self.corpus["scope"]["entry_count"], 158)
        self.assertEqual(len(self.entries), 158)
        for ordinal, entry in self.entries.items():
            self.assertRegex(entry["source_text_sha256"], r"^[0-9a-f]{64}$")
            if ordinal in (34, 124):
                self.assertEqual(entry["editorial_status"], "final")
                self.assertEqual(entry["translation_action"], "preserve")
            else:
                self.assertEqual(entry["editorial_status"], "reviewed")

    def test_human_decisions_and_consistency_override_remain_explicit(self):
        expected = {
            1: "升空功能",
            8: "魔神力",
            9: "古连泰沙全功率",
            16: "完全抗性",
            23: "重力子临界",
            26: "精神感应力场",
            33: "防护力场",
            38: "积层装甲",
            45: "马赫特技",
        }
        self.assertEqual(
            {ordinal: self.entries[ordinal]["translation"] for ordinal in expected},
            expected,
        )
        self.assertIn("强化零件审核", self.entries[33]["notes"])

    def test_all_ability_names_have_one_approved_matching_glossary_binding(self):
        ability_ordinals = [*range(34), *range(35, 46)]
        self.assertEqual(len(ability_ordinals), 45)
        for ordinal in ability_ordinals:
            entry = self.entries[ordinal]
            matches = [
                term
                for reference in entry.get("glossary_refs", [])
                for term in self.glossary.get(reference, [])
                if term.get("translation") == entry["translation"]
                and term.get("status") == "approved"
            ]
            self.assertEqual(
                len(matches),
                1,
                f"ordinal {ordinal} glossary binding: {entry.get('glossary_refs')}",
            )

    def test_companion_menu_help_and_battle_surfaces_are_consistent(self):
        remaining = load(REMAINING_UI_PATH)
        direct_expected = {
            "0x740F0": "龙骑兵屏障",
            "0x74160": "防护力场",
            "0x74198": "积层装甲",
            "0x74200": "马赫特技",
            "0x74238": "剑装备",
            "0x74240": "盾装备",
            "0x74270": "魔神力",
        }
        self.assertEqual(
            {
                offset: remaining["compdata_direct_by_offset"][offset]
                for offset in direct_expected
            },
            direct_expected,
        )
        self.assertEqual(remaining["slps_by_offset"]["0x33E4E0"], "马赫特技")
        for offset in ("0x73F20", "0x77970", "0x77C20"):
            help_text = remaining["compdata_context_help_by_offset"][offset]
            self.assertIn("升空功能", help_text)
            self.assertNotIn("飞行功能", help_text)

        search = {row["id"]: row for row in load(SEARCH_UI_PATH)["entries"]}
        self.assertEqual(search["menu/Compdata/06/0012"]["translation"], "升空功能")
        self.assertEqual(search["menu/Compdata/06/0012"]["editorial_status"], "reviewed")

        battle = {row["id"]: row for row in load(BATTLE_PATH)["entries"]}
        battle_expected = {
            "battle:00389": "“除非将魔神力作为魔神使用……”",
            "battle:17725": "“没发现！\\n　是积层装甲的效果！”",
            "battle:17727": "“没关系，\\n　积层装甲没有被击破”",
            "battle:22695": "“魔神力，全功率！”",
            "battle:24496": "“马赫特技！！”",
        }
        self.assertEqual(
            {record_id: battle[record_id]["translation"] for record_id in battle_expected},
            battle_expected,
        )

    def test_barrier_field_matches_the_approved_part_term(self):
        parts = {term["id"]: term for term in load(PARTS_GLOSSARY_PATH)["terms"]}
        barrier = parts["part/barrier-field"]
        self.assertEqual(barrier["translation"], "防护力场")
        self.assertEqual(barrier["status"], "approved")
        self.assertEqual(self.entries[33]["translation"], barrier["translation"])

    def test_numeric_en_costs_do_not_insert_a_full_cell_gap(self):
        for ordinal, entry in self.entries.items():
            self.assertIsNone(
                re.search(r"消耗\d+ EN", entry["translation"]),
                msg=f"ordinal {ordinal} keeps an oversized EN gap",
            )
        self.assertIn("消耗10EN。", self.entries[83]["translation"])

        remaining = load(REMAINING_UI_PATH)
        self.assertIn(
            "消耗10EN。",
            remaining["compdata_direct_by_offset"]["0x7D6F0"],
        )

    def test_final_iso_binds_every_reviewed_special_ability(self):
        content = load(CONTENT_PATH)
        report = content["compdata"]["special_abilities"]
        self.assertEqual(report["corpus_entry_count"], 158)
        self.assertEqual(report["translated_entry_count"], 156)
        self.assertEqual(report["preserved_structure_entry_count"], 2)
        self.assertEqual(report["target_occurrence_count"], 194)
        self.assertEqual(report["unique_target_count"], 159)
        self.assertEqual(report["raw_visible_ascii_glyph_count"], 0)
        self.assertEqual(report["raw_visible_ascii_target_count"], 0)
        self.assertEqual(report["raw_space_target_count"], 0)
        self.assertTrue(report["source_preimages_sha256_exact"])
        self.assertTrue(report["target_offset_readback_exact"])
        self.assertEqual(report["vps_armor"]["readback"], "VPS装甲")
        self.assertEqual(
            report["vps_armor"]["stored_prefix_hex"],
            "8275826f8272",
        )
        self.assertTrue(report["vps_armor"]["two_byte_latin_storage"])

    def test_all_ability_and_weapon_effect_fields_reject_raw_visible_ascii(self):
        content = load(CONTENT_PATH)
        audit = content["ability_visible_ascii_audit"]
        expected_counts = {
            "pilot_special_skills": (88, 92, 88),
            "mech_special_abilities": (158, 194, 159),
            "unit_mech_pilot_weapon_ui": (104, 113, 112),
            "weapon_special_effect_1": (8, 8, 8),
        }
        for label, (entries, occurrences, targets) in expected_counts.items():
            report = audit[label]
            entry_key = (
                "corpus_entry_count"
                if label == "mech_special_abilities"
                else "entry_count"
            )
            self.assertEqual(report[entry_key], entries)
            self.assertEqual(report["target_occurrence_count"], occurrences)
            self.assertEqual(report["unique_target_count"], targets)
            self.assertEqual(report["raw_visible_ascii_glyph_count"], 0)
            self.assertEqual(report["raw_visible_ascii_target_count"], 0)
            self.assertEqual(report["raw_space_target_count"], 0)

        labels = audit["weapon_special_effect_labels"]
        self.assertEqual(labels["entry_count"], 2)
        self.assertEqual(labels["raw_visible_ascii_glyph_count"], 0)
        self.assertEqual(labels["raw_visible_ascii_target_count"], 0)

        help_report = audit["weapon_special_effect_help"]
        self.assertEqual(help_report["entry_count"], 7)
        self.assertEqual(help_report["raw_visible_ascii_glyph_count"], 0)
        self.assertEqual(help_report["raw_visible_ascii_target_count"], 0)

        effect_2 = audit["weapon_special_effect_2"]
        self.assertEqual(effect_2["term_count"], 2)
        self.assertEqual(effect_2["occurrence_count"], 6)
        self.assertEqual(effect_2["raw_visible_ascii_glyph_count"], 0)
        self.assertEqual(effect_2["raw_visible_ascii_target_count"], 0)
        self.assertEqual(effect_2["raw_space_target_count"], 0)
        self.assertTrue(audit["runtime_control_tokens_excluded"])
        self.assertTrue(
            audit["all_checked_fields_use_two_byte_visible_ascii"]
        )
        self.assertTrue(
            content["checks"]["ability_visible_ascii_storage_exact"]
        )


if __name__ == "__main__":
    unittest.main()
