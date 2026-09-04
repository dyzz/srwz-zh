from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from srwz.chinese_layout import dialogue_line_widths  # noqa: E402


def load_entries(relative_path: str) -> dict[str, str]:
    payload = json.loads((PROJECT_ROOT / relative_path).read_text(encoding="utf-8"))
    return {entry["id"]: entry["translation"] for entry in payload["entries"]}


class CommunityFeedbackStage055Test(unittest.TestCase):
    def test_accepted_stage_055_feedback_has_confirmed_wording_and_layout(self) -> None:
        entries = load_entries("corpus/zh/story-dialogue/stage-055.json")
        expected = {
            "story/055/dialogue/01.22/0008": (
                "“所以我才叫你回去！嘴上说着不想战斗，\n"
                "　你现在又是在干什么！？”"
            ),
            "story/055/dialogue/01.47/0001": (
                "“住手吧，奥布军！\n　奥布还有什么理由要战斗！？”"
            ),
            "story/055/dialogue/01.47/0003": (
                "“不能攻击！他们并不是我们的敌人！\n"
                "　奥布绝不能攻击他们！”"
            ),
            "story/055/dialogue/01.47/0004": (
                "“……不许停止战斗！\n　这是命令……！”"
            ),
            "story/055/dialogue/01.47/0005": (
                "“我国现任领导人\n　尤纳·罗马·塞兰的命令！”"
            ),
            "story/055/dialogue/01.47/0007": (
                "“那么，那就是国家的意志！\n"
                "　既然如此，我们奥布军人的职责\n"
                "　就是服从！”"
            ),
            "story/055/dialogue/01.47/0009": (
                "“无论那条路有何不同、多么艰难，\n"
                "　我们都必须坚守这一点！\n"
                "　明白了吗啊啊！”"
            ),
            "story/055/dialogue/01.50/0005": (
                "“非要说这一切都是奥布和卡嘉莉的错，\n"
                "　然后对现在卡嘉莉想守护的东西\n"
                "　下手不可吗！”"
            ),
            "story/055/dialogue/01.50/0007": "“那么，我……就要打倒你！”",
        }
        self.assertEqual(
            {entry_id: entries[entry_id] for entry_id in expected},
            expected,
        )
        for entry_id, translation in expected.items():
            widths = dialogue_line_widths(translation)
            self.assertLessEqual(len(widths), 3, entry_id)
            self.assertLessEqual(max(widths), 21, entry_id)

    def test_accepted_battle_feedback_uses_natural_character_voice(self) -> None:
        entries = load_entries("corpus/zh/battle/srvc-lines.json")
        expected = {
            "battle:04183": "“沉下去吧！！”",
            "battle:04721": "“连眼前的状况都看不明白吗！？”",
            "battle:05884": "“唔！我还没倒下呢！”",
            "battle:05976": "“至少也要由我亲手\\n　了结你的罪业！”",
            "battle:05992": "“就是那里！！”",
            "battle:08086": "“只要近到这个距离，就是我的天下了！”",
            "battle:08087": "“这招打不偏！”",
            "battle:08097": "“别想跑！就在这儿击落你！”",
            "battle:08110": "“绝不能让多戈斯·基亚\\n　沉没！”",
            "battle:08111": "“切，西罗克这家伙！\\n　居然拿我当盾牌！”",
            "battle:15710": "“12点方向，敌部队仍具战斗力！”",
        }
        self.assertEqual(
            {entry_id: entries[entry_id] for entry_id in expected},
            expected,
        )


if __name__ == "__main__":
    unittest.main()
