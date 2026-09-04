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


if __name__ == "__main__":
    unittest.main()
