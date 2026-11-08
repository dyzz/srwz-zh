from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from srwz.build_layout import verify_stored
from srwz.chinese_layout import dialogue_line_widths  # noqa: E402


def load_entries(relative_path: str) -> dict[str, str]:
    payload = json.loads((PROJECT_ROOT / relative_path).read_text(encoding="utf-8"))
    return {entry["id"]: entry["translation"] for entry in payload["entries"]}


class CommunityFeedbackStage055Test(unittest.TestCase):
    def test_accepted_stage_055_feedback_has_confirmed_wording_and_layout(self) -> None:
        entries = load_entries("corpus/zh/story-dialogue/stage-055.json")
        expected = {
            "story/055/dialogue/01.22/0008": (
                '“所以我才叫你回去！嘴上说着不想战斗，你现在又\n\u3000是在干什么！？”'
            ),
            "story/055/dialogue/01.47/0001": (
                '“住手吧，奥布军！奥布还有什么理由要战斗！？”'
            ),
            "story/055/dialogue/01.47/0003": (
                '“不能攻击！他们并不是我们的敌人！奥布绝不能攻\n\u3000击他们！”'
            ),
            "story/055/dialogue/01.47/0004": (
                '“……我不可能中途脱离战斗！这可是命令\n\u3000啊……！”'
            ),
            "story/055/dialogue/01.47/0005": (
                '“我国现任领导人尤纳·罗马·塞兰的命令！”'
            ),
            "story/055/dialogue/01.47/0007": (
                '“那么，那就是国家的意志！既然如此，我们奥布军\n\u3000人的职责就是服从！”'
            ),
            "story/055/dialogue/01.47/0009": (
                '“无论那条路有何不同、多么艰难，我们都必须坚守\n\u3000这一点！明白了吗啊啊！”'
            ),
            "story/055/dialogue/01.50/0005": (
                '“非要说这一切都是奥布和卡嘉莉的错，然后对现在\n\u3000卡嘉莉想守护的东西下手不可吗！”'
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
            self.assertEqual(verify_stored([(entry_id, translation, False)], "story"), 1)

    def test_accepted_battle_feedback_uses_natural_character_voice(self) -> None:
        entries = load_entries("corpus/zh/battle/srvc-lines.json")
        expected = {
            "battle:04183": "“沉下去吧！！”",
            "battle:04721": "“连眼前的状况都看不明白吗！？”",
            "battle:05884": "“唔！我还没倒下呢！”",
            "battle:05976": '“至少也要由我亲手了结你的罪\\n\u3000业！”',
            "battle:05992": "“就是那里！！”",
            "battle:08086": "“只要近到这个距离，就是我的天下了！”",
            "battle:08087": "“这招打不偏！”",
            "battle:08097": "“别想跑！就在这儿击落你！”",
            "battle:08110": '“绝不能让多戈斯·基亚沉\\n\u3000没！”',
            "battle:08111": '“切，西罗克这家伙！居然拿我当盾\\n\u3000牌！”',
            "battle:15710": "“12点方向，敌部队仍具战斗力！”",
        }
        self.assertEqual(
            {entry_id: entries[entry_id] for entry_id in expected},
            expected,
        )


if __name__ == "__main__":
    unittest.main()
