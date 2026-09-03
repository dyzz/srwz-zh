from __future__ import annotations

import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class CommunityFeedbackBattleRound4Test(unittest.TestCase):
    def test_accepted_feedback_keeps_conservative_natural_wording(self) -> None:
        payload = json.loads(
            (PROJECT_ROOT / "corpus/zh/battle/srvc-lines.json").read_text(
                encoding="utf-8"
            )
        )
        entries = {entry["id"]: entry["translation"] for entry in payload["entries"]}
        expected = {
            "battle:02221": "“BIG-FAU，行动！”",
            "battle:09144": "“不疼…只是痛苦而已！”",
            "battle:09166": "“把情报透露给我就是你的失算！”",
            "battle:09197": "“这世上有防护罩这种东西！”",
            "battle:16166": "“我要直击你~！！”",
            "battle:21271": "“这个舞台也就此谢幕了。”",
            "battle:21281": "“无论哪个时代，\\n　总有试图用暴力解决问题的人！”",
            "battle:21285": "“那要看对象。\\n　这种情况，没那个必要！”",
            "battle:21293": "“我这人挺爱管闲事的。”",
            "battle:21352": "“是啊。\\n　不过，比不上你的钢琴。”",
        }
        self.assertEqual(
            {entry_id: entries[entry_id] for entry_id in expected},
            expected,
        )


if __name__ == "__main__":
    unittest.main()
