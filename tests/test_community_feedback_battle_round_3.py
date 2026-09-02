from __future__ import annotations

import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class CommunityFeedbackBattleRound3Test(unittest.TestCase):
    def test_accepted_feedback_uses_natural_conservative_wording(self) -> None:
        payload = json.loads(
            (PROJECT_ROOT / "corpus/zh/battle/srvc-lines.json").read_text(
                encoding="utf-8"
            )
        )
        entries = {entry["id"]: entry["translation"] for entry in payload["entries"]}
        expected = {
            "battle:01856": "“卡洛德，\\n　气势不错，但收尾还不到家！”",
            "battle:01858": "“把MS的性能发挥出来，真！”",
            "battle:01865": "“让机体上前！明白吗，中尉！”",
            "battle:01880": "“真是台好机体…\\n　能跟上我的反应。”",
            "battle:01889": "“中计了吧，西罗克！”",
            "battle:01917": "“帕普提马斯·西罗克…！\\n　我要压制住你的压迫感！”",
            "battle:01918": "“西罗克！世界还没小到\\n　只凭几个天才就能改变的地步！”",
            "battle:01922": "“只要破坏塞可缪系统，\\n　之后就…！”",
            "battle:01929": "“基姆·金卡拉姆！你那番妄言…！”",
            "battle:01931": "“你们的私欲…我绝不认可！”",
            "battle:01999": "“我不能认同你的私欲！”",
            "battle:02009": "“基拉，接下来交给我！”",
            "battle:10096": "“夏亚！要知道推动世界的\\n　向来只是极少数的天才！！”",
            "battle:20739": "“趁机击破！”",
            "battle:21473": "“克瓦特罗上尉，那个位置不行！”",
        }
        self.assertEqual(
            {entry_id: entries[entry_id] for entry_id in expected},
            expected,
        )


if __name__ == "__main__":
    unittest.main()
