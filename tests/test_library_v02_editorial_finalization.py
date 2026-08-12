import json
import unittest
from pathlib import Path

from tools import finalize_library_v02_editorial_decisions as finalization


PROJECT_ROOT = Path(__file__).resolve().parents[1]
KEYWORD_DECISIONS = {
    "136ce92019050a30178d10f99e5a203b0ab29fdfc8c45915b92cbb2700841755": "外套",
    "3ab1d170216943f8e4c50babe68398c8a08439151283848c452df3aabf29aecd": "超限人对战",
    "4b415e28391c3157a439f38a6ccf7f3b9b7b418ec86dacea9aec6312927fe536": "曙光社",
    "52a93e848e7ff3b5013a381db10e590999e67c5f27928f7685cee2b03e293568": "奥古",
    "9f8a9b5812a6b6860d84923d3f46355e5a42b1572d0287e444569fe7fb59048c": "滑空",
    "fa58a7465ca02955e208ff77b2f4c36f3d70dcc48b368d5b44933d6f70fc9bad": "平衡轮",
}


class LibraryV02EditorialFinalizationTests(unittest.TestCase):
    def test_normalized_source_ignores_game_hard_wraps(self):
        self.assertEqual(
            finalization.normalized_source("　同じ\n原文"),
            finalization.normalized_source("同じ原文"),
        )

    def test_known_bad_substrings_include_duplicate_joiners(self):
        self.assertIn("与与", finalization.KNOWN_BAD_SUBSTRINGS)
        self.assertIn("赤骑士赤骑士", finalization.KNOWN_BAD_SUBSTRINGS)
        self.assertIn("新地球联邦军军人", finalization.KNOWN_BAD_SUBSTRINGS)
        self.assertIn("迪安娜反击军军曹", finalization.KNOWN_BAD_SUBSTRINGS)

    def test_runtime_keyword_decisions_are_source_hash_pinned_in_library(self):
        overrides = json.loads(
            (PROJECT_ROOT / "config/library/v0.2-editorial-overrides.json").read_text(
                encoding="utf-8"
            )
        )
        reviewed = json.loads(
            (PROJECT_ROOT / "corpus/zh/library/v0.2-reviewed.json").read_text(
                encoding="utf-8"
            )
        )
        override_by_hash = {
            row["source_text_sha256"]: row for row in overrides["entries"]
        }
        reviewed_by_hash = {
            row["source_text_sha256"]: row for row in reviewed["entries"]
        }
        self.assertEqual(
            {
                source_hash: override_by_hash[source_hash]["translation"]
                for source_hash in KEYWORD_DECISIONS
            },
            KEYWORD_DECISIONS,
        )
        self.assertEqual(
            {
                source_hash: reviewed_by_hash[source_hash]["translation"]
                for source_hash in KEYWORD_DECISIONS
            },
            KEYWORD_DECISIONS,
        )
        self.assertTrue(
            all(
                reviewed_by_hash[source_hash]["review_origin"]
                == "manual_source_verified_override"
                for source_hash in KEYWORD_DECISIONS
            )
        )


if __name__ == "__main__":
    unittest.main()
