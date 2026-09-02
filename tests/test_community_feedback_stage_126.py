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


class CommunityFeedbackStage126Test(unittest.TestCase):
    def test_accepted_story_feedback_has_natural_wording_and_layout(self) -> None:
        entries = load_entries("corpus/zh/story-dialogue/stage-126.json")
        expected = {
            "story/126/dialogue/01.02/0002": (
                "“男人……？\n　我觉得问题不在这里……”"
            ),
            "story/126/dialogue/01.03/0002": (
                "“今后，她大概会动真格，\n　把拒绝她的我们消灭掉吧。”"
            ),
            "story/126/dialogue/01.05/0000": (
                "“哈曼·卡恩……！\n　竟敢擅自与$c会谈，\n　甚至还挑起战斗！”"
            ),
            "story/126/dialogue/01.13/0004": (
                "“居然不先对付那门大炮，而是我们，\n"
                "　你也太看得起我们了，大哥。”"
            ),
            "story/126/dialogue/01.14/0001": "“戴眼镜的大哥来了！”",
        }
        self.assertEqual(
            {entry_id: entries[entry_id] for entry_id in expected},
            expected,
        )
        for entry_id, translation in expected.items():
            widths = dialogue_line_widths(translation)
            self.assertLessEqual(len(widths), 3, entry_id)
            self.assertLessEqual(max(widths), 21, entry_id)

    def test_accepted_battle_feedback_preserves_conservative_meaning(self) -> None:
        entries = load_entries("corpus/zh/battle/srvc-lines.json")
        expected = {
            "battle:01838": "“那种动作可不行！”",
            "battle:01840": "“这个位置的话，还能再来一击！”",
            "battle:01843": "“友军后退！我要启动月光蝶！”",
            "battle:01845": "“没办法！启动月光蝶！”",
            "battle:01848": "“这种配合，你逃不掉！”",
            "battle:01850": "“这里是阿姆罗。我来支援！”",
            "battle:01910": "“别想碍事！”",
            "battle:01953": "“看我把你击落！”",
            "battle:05997": "“只是擦到而已！”",
            "battle:07672": "“看这一击！”",
            "battle:07708": "“不会让卡兹出事的！”",
            "battle:07748": "“卡兹，\\n　凭那种火力的机体…！”",
            "battle:08123": "“给我从基础训练重新来过！”",
            "battle:08126": "“哈！看来你生疏了不少啊！”",
            "battle:08135": "“怎么了，卡缪！你就只有这种水平吗！”",
            "battle:08147": "“难道凭这台机体！\\n　我就赢不了那家伙吗！”",
            "battle:08151": "“为什么高达还这么精神啊！？”",
            "battle:08167": "“可恶，到此为止了吗！！”",
            "battle:08210": "“Z高达，给我坠落吧！！”",
            "battle:10001": "“违逆时代潮流的人，就此消失吧！”",
            "battle:10003": "“坠落吧！小虫！！”",
            "battle:10005": "“你的存在本身就很碍眼！”",
            "battle:10006": "“位置选得不错…\\n　正好把你击落！”",
            "battle:10015": "“让这烦人的压迫感消失吧！”",
            "battle:10033": "“坠落吧，你们这些小虫…！”",
            "battle:10036": "“进不了我的领域吗…！”",
            "battle:10046": "“只有你才与众不同的时代\\n　已经结束了”",
            "battle:10047": "“！？有话语一闪而过！”",
            "battle:10048": "“有话语一闪而过…！\\n　敌人是新人类吗！”",
            "battle:10071": "“唔！这股精神感应冲击！”",
            "battle:10075": "“为什么攻击会接连命中！？”",
            "battle:10076": "“怎么了，铁奥！？\\n　为什么不听话！？”",
            "battle:10081": "“坠落吧，小虫！”",
            "battle:10086": "“只会耍小聪明的小鬼！消失吧！！”",
            "battle:10101": "“这些小虫！\\n　老是在我周围飞来飞去！”",
            "battle:10109": "“只会耍小聪明的小鬼，还敢说什么！！”",
            "battle:15107": "“我可也是个驾驶员啊！”",
            "battle:17325": "“避开直击了吗…！”",
            "battle:20737": "“哈曼！我不会让你干掉西罗克！”",
            "battle:20762": "“回避成功！准备应对下次攻击！”",
            "battle:21468": "“花，不用勉强自己！”",
            "battle:21474": "“爱玛中尉，快撤离！”",
            "battle:21481": "“收到，我来牵制！”",
            "battle:21484": "“给我坠下去！！”",
            "battle:21490": "“会被那招打中的，都是外行。”",
            "battle:21505": "“提坦斯，别得意忘形！”",
        }
        self.assertEqual(
            {entry_id: entries[entry_id] for entry_id in expected},
            expected,
        )


if __name__ == "__main__":
    unittest.main()
