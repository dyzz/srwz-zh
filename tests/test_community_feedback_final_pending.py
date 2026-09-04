from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from srwz.chinese_layout import dialogue_line_widths  # noqa: E402


def load_payload(relative_path: str) -> dict:
    return json.loads((PROJECT_ROOT / relative_path).read_text(encoding="utf-8"))


class CommunityFeedbackFinalPendingTest(unittest.TestCase):
    def test_confirmed_battle_feedback_has_final_wording_and_layout(self) -> None:
        payload = load_payload("corpus/zh/battle/srvc-lines.json")
        entries = {entry["id"]: entry for entry in payload["entries"]}
        expected = {
            "battle:00145": "“搞什么啊！\\n　装甲都让你给干瘪了！”",
            "battle:01927": "“吉尔伯特·迪兰达尔…\\n　你只会居高临下地看待一切！”",
            "battle:02016": "“生物传感器有反应了…！好…！”",
            "battle:03315": "“就那么上—！”",
            "battle:04682": "“光会瞄准可不够！”",
            "battle:05905": "“那股力量！！”",
            "battle:08088": "“老子要打穿你！”",
            "battle:08090": "“哼，休想逃！”",
            "battle:08216": "“什么！？拜亚兰被！？”",
            "battle:08242": "“光是新人类的存在，\\n　就让人感到压力！”",
            "battle:10192": "“琪露，有点危险千万别露头喔！”",
            "battle:13654": "“把你轰下来！”",
            "battle:15735": "“居住区附近发生火灾！\\n　非战斗员应该平安无事！”",
            "battle:16187": "“让你见识…东洋的神力！”",
            "battle:21365": "“真是个该死的对手。”",
            "battle:21451": "“阿萨基姆！奉神之名宣告汝之罪孽！\\n　汝，罪无可赦！”",
        }
        self.assertEqual(
            {entry_id: entries[entry_id]["translation"] for entry_id in expected},
            expected,
        )
        for entry_id, translation in expected.items():
            widths = dialogue_line_widths(translation.replace("\\n", "\n"))
            self.assertLessEqual(max(widths), 21, entry_id)

    def test_corrective_translation_records_both_source_editions(self) -> None:
        payload = load_payload("corpus/zh/battle/srvc-lines.json")
        entries = {entry["id"]: entry for entry in payload["entries"]}
        notes = entries["battle:08242"]["notes"]
        for marker in (
            "SLPS_258.87",
            "SLPS_732.70",
            "The Best",
            "いない",
            "いる",
            "原文纠错性定稿",
        ):
            self.assertIn(marker, notes)

    def test_confirmed_story_feedback_and_retained_context_note(self) -> None:
        stage_031 = load_payload("corpus/zh/story-dialogue/stage-031.json")
        entries_031 = {entry["id"]: entry for entry in stage_031["entries"]}
        self.assertEqual(
            entries_031["story/031/dialogue/01.33/0003"]["translation"],
            "“冷静点！你想成为杀人狂吗！？”",
        )

        stage_055 = load_payload("corpus/zh/story-dialogue/stage-055.json")
        entries_055 = {entry["id"]: entry for entry in stage_055["entries"]}
        retained = entries_055["story/055/dialogue/01.50/0004"]
        self.assertEqual(
            retained["translation"],
            "“可你却要说这场战斗和牺牲都是不得已……”",
        )
        for marker in ("卡嘉莉因牺牲痛哭", "なのに", "非要", "全都", "避免超出原文"):
            self.assertIn(marker, retained["notes"])

    def test_category_f_is_a_classification_in_every_current_surface(self) -> None:
        glossary = load_payload("corpus/glossary/skills-v1.json")
        category_f = next(
            entry for entry in glossary["terms"] if entry["id"] == "skill/category-f"
        )
        self.assertEqual(category_f["translation"], "F类")
        self.assertEqual(category_f["domains"], ["menu", "story", "battle", "library"])
        for marker in ("Flash System", "Newtype", "Category F", "Fake", "研究分类", "F等级"):
            self.assertIn(marker, category_f["notes"])

        menu = load_payload("corpus/zh/menu/system-ui-skills.json")
        menu_entries = {entry["id"]: entry for entry in menu["entries"]}
        self.assertEqual(menu_entries["menu/SLPS/09/0069"]["translation"], "F类")

        expected_story = {
            "story/068/dialogue/02.01/0213": "“情报部的特工吗……我记得是被\n　称为F类的失败的新人类……”",
            "story/076/dialogue/02.04/0012": "“F类！”",
            "story/076/dialogue/02.04/0015": "“创造未来的不是新人类。\n　而是被称为F类的我们。”",
            "story/097/dialogue/02.01/0226": "“情报部的特工吗……\n　听说是什么F类的新人类残次品……”",
            "story/119/dialogue/01.15/0002": "“F类！你们这些失败的新人类！”",
            "story/119/dialogue/01.15/0004": "“F类……没能成为新人类的人……”",
            "story/119/dialogue/01.19/0042": "“仅仅因为这个理由，我们被称为F类，\n　被打上了无能的烙印！”",
            "story/127/dialogue/01.17/0002": "“F类！不成器的新人类！”",
            "story/127/dialogue/01.17/0004": "“F类……没能成为新人类的人……”",
            "story/127/dialogue/01.21/0043": "“仅仅因为那个理由，我们就被称为F类，\n　被打上了无能的烙印！”",
            "story/127/dialogue/01.38/0015": "“我对你们这些不成器的家伙可\n　没抱过分的期待，F类。”",
            "story/130/dialogue/01.09/0003": "“人类就是这样啊。也难怪西利乌斯\n　和F类的兄弟们会绝望。”",
            "story/135/dialogue/02.01/0175": "“关于所谓F类者的报告，我也听说过。”",
            "story/138/dialogue/02.01/0179": "“关于所谓F类者的报告，我也听说过”",
        }
        actual_story = {}
        for stage_index in (68, 76, 97, 119, 127, 130, 135, 138):
            stage = load_payload(f"corpus/zh/story-dialogue/stage-{stage_index:03d}.json")
            for entry in stage["entries"]:
                if "skill/category-f" in entry.get("glossary_refs", []):
                    actual_story[entry["id"]] = entry["translation"]
        self.assertEqual(actual_story, expected_story)
        for entry_id, translation in expected_story.items():
            self.assertLessEqual(max(dialogue_line_widths(translation)), 21, entry_id)

        battle = load_payload("corpus/zh/battle/srvc-lines.json")
        battle_entries = {entry["id"]: entry for entry in battle["entries"]}
        expected_battle = {
            "battle:08667": "“创造未来的不是你们…\\n　而是被称为F类的我们”",
            "battle:08684": "“难道要说F类\\n　比新人类差吗！”",
        }
        for entry_id, translation in expected_battle.items():
            self.assertEqual(battle_entries[entry_id]["translation"], translation)
            self.assertIn("skill/category-f", battle_entries[entry_id]["glossary_refs"])
            self.assertLessEqual(
                max(dialogue_line_widths(translation.replace("\\n", "\n"))),
                21,
                entry_id,
            )

        library = load_payload("corpus/zh/library/v0.2-reviewed.json")
        library_entries = [
            entry
            for entry in library["entries"]
            if "skill/category-f" in entry.get("glossary_refs", [])
        ]
        self.assertEqual(len(library_entries), 4)
        for entry in library_entries:
            self.assertIn("F类", entry["translation"])
            self.assertNotIn("伪新人类", entry["translation"])

    def test_spazer_family_stays_unified_and_breast_fire_is_restored(self) -> None:
        unit_glossary = load_payload(
            "corpus/glossary/story-dialogue-stage-006-v1.json"
        )
        unit_terms = {entry["id"]: entry for entry in unit_glossary["terms"]}
        expected_units = {
            "unit/spazer": "飞天神机",
            "unit/double-spazer": "双重飞天神机",
            "unit/marine-spazer": "海洋飞天神机",
            "unit/drill-spazer": "钻头飞天神机",
        }
        self.assertEqual(
            {entry_id: unit_terms[entry_id]["translation"] for entry_id in expected_units},
            expected_units,
        )
        self.assertIn("斯派扎", unit_terms["unit/spazer"]["deprecated_translations"])
        self.assertIn(
            "双重斯派扎",
            unit_terms["unit/double-spazer"]["deprecated_translations"],
        )
        for marker in ("专用圆盘型机械", "合体形态", "不与“斯派扎”音译混用"):
            self.assertIn(marker, unit_terms["unit/spazer"]["notes"])

        weapon_glossary = load_payload("corpus/glossary/weapons-v1.json")
        weapon_terms = {entry["id"]: entry for entry in weapon_glossary["terms"]}
        breast_fire = weapon_terms["weapon/0007"]
        self.assertEqual(breast_fire["translation"], "胸部火焰")
        self.assertIn("胸甲烈焰", breast_fire["deprecated_translations"])
        self.assertNotIn("胸部火焰", breast_fire["deprecated_translations"])

        menu = load_payload("corpus/zh/menu/weapons.json")
        menu_entries = {entry["id"]: entry for entry in menu["entries"]}
        self.assertEqual(menu_entries["menu/Compdata/02/0007"]["translation"], "胸部火焰")

        battle = load_payload("corpus/zh/battle/srvc-lines.json")
        battle_entries = {entry["id"]: entry for entry in battle["entries"]}
        expected_battle = {
            "battle:07273": "“胸部火焰！！”",
            "battle:20161": "“胸部火焰！”",
        }
        for entry_id, translation in expected_battle.items():
            self.assertEqual(battle_entries[entry_id]["translation"], translation)
            self.assertIn("weapon/0007", battle_entries[entry_id]["glossary_refs"])
            self.assertLessEqual(max(dialogue_line_widths(translation)), 21, entry_id)

        library = load_payload("corpus/zh/library/v0.2-reviewed.json")
        library_entry = next(
            entry
            for entry in library["entries"]
            if entry["id"] == "library-text/1b2ed9e8e9afc711"
        )
        self.assertIn("胸部火焰", library_entry["translation"])
        self.assertNotIn("胸甲烈焰", library_entry["translation"])
        self.assertIn("weapon/0007", library_entry["glossary_refs"])


if __name__ == "__main__":
    unittest.main()
