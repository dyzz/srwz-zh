import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORPUS = PROJECT_ROOT / "corpus"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def iter_records(value):
    if isinstance(value, dict):
        if isinstance(value.get("id"), str) and isinstance(value.get("translation"), str):
            yield value
        for child in value.values():
            yield from iter_records(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_records(child)


class CombinedTextReviewTranslationTests(unittest.TestCase):
    def test_reviewed_glossary_choices_are_canonical(self):
        expected = {
            "skill/category-f": "伪新人类",
            "skill/extended": "强化人SEED",
            "spirit/cheer": "应援",
            "spirit/flash": "必闪",
            "system/enhancement-part": "强化零件",
        }
        found = {}
        for path in (PROJECT_ROOT / "corpus/glossary").glob("*.json"):
            for term in read_json(path).get("terms", []):
                if term.get("id") in expected:
                    found[term["id"]] = (term.get("translation"), term.get("status"))
        self.assertEqual(found, {key: (value, "approved") for key, value in expected.items()})

    def test_glossary_bound_surfaces_use_reviewed_terms(self):
        rules = {
            "skill/category-f": ("F类型", "伪新人类", 15),
            "skill/extended": ("Extended", "强化人SEED", 20),
            "spirit/cheer": ("声援", "应援", 2),
            "system/enhancement-part": ("强化部件", "强化零件", 11),
        }
        records = []
        for path in (PROJECT_ROOT / "corpus/zh").rglob("*.json"):
            records.extend(iter_records(read_json(path)))
        for term_id, (old, new, expected_count) in rules.items():
            targets = [row for row in records if term_id in row.get("glossary_refs", [])]
            self.assertEqual(len(targets), expected_count, term_id)
            self.assertTrue(all(old not in row["translation"] for row in targets), term_id)
            self.assertTrue(all(new in row["translation"] for row in targets), term_id)

    def test_superseded_canonical_forms_are_absent(self):
        text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(CORPUS.rglob("*.json"))
        )
        for stale in ("F类型", "Extended", "强化部件"):
            self.assertNotIn(stale, text)
        # Generic cheering in dialogue/summary/battle is not the spirit-command name.
        self.assertEqual(text.count("声援"), 5)

    def test_selected_copy_edits_are_present(self):
        skills = {row["id"]: row for row in read_json(PROJECT_ROOT / "corpus/zh/menu/system-ui-skills.json")["entries"]}
        spirits = {row["id"]: row for row in read_json(PROJECT_ROOT / "corpus/zh/menu/system-ui-spirit-commands.json")["entries"]}
        leadership = {row["id"]: row for row in read_json(PROJECT_ROOT / "corpus/zh/menu/system-ui-leadership.json")["entries"]}
        self.assertEqual(
            skills["menu/SLPS/09/0009"]["translation"],
            "可为相邻小队的队长进行援护攻击。\n每回合最多发动与技能等级相同的次数。",
        )
        self.assertEqual(
            spirits["menu/SLPS/08/0054"]["translation"],
            "本小队可行动次数增加1次。\n不可叠加使用。",
        )
        self.assertEqual(
            spirits["menu/SLPS/08/0013"]["translation"], "必闪"
        )
        self.assertIn(
            "必闪", spirits["menu/SLPS/08/0012"]["translation"]
        )
        self.assertEqual(leadership["menu/Compdata/05/0011"]["translation"], "回复量提升")


if __name__ == "__main__":
    unittest.main()
