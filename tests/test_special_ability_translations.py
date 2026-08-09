import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORPUS_PATH = PROJECT_ROOT / "corpus/zh/menu/system-ui-special-abilities.json"
GLOSSARY_ROOT = PROJECT_ROOT / "corpus/glossary"
PARTS_GLOSSARY_PATH = GLOSSARY_ROOT / "parts-v1.json"
REMAINING_UI_PATH = PROJECT_ROOT / "corpus/zh/menu/remaining-ui.json"
SEARCH_UI_PATH = PROJECT_ROOT / "corpus/zh/menu/system-ui-search.json"
BATTLE_PATH = PROJECT_ROOT / "corpus/zh/battle/srvc-lines.json"


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


if __name__ == "__main__":
    unittest.main()
