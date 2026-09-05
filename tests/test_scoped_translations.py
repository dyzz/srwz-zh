import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from srwz.scoped_translations import (
    load_scoped_translations, resolve_scoped_translation,
    verify_scoped_translation_coverage,
)


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


class ScopedTranslationTests(unittest.TestCase):
    def setUp(self):
        self.row = dict(id="character/408/ACTR", source_text_sha256=sha("千葉一伸"),
                        context_text_sha256=sha("シュラン・オペル"), translation="松本吉朗")
        self.overrides = load_scoped_translations([self.row])

    def test_corrects_only_the_target_character_and_field(self):
        self.assertEqual(resolve_scoped_translation(self.overrides, "character/408/ACTR",
                         "千葉一伸", "千叶一伸", context_text="シュラン・オペル"), "松本吉朗")
        for entry in ("character/225/ACTR", "character/408/CHFN"):
            self.assertEqual(resolve_scoped_translation(self.overrides, entry, "千葉一伸", "千叶一伸"), "千叶一伸")

    def test_changed_source_or_character_cannot_silently_use_override(self):
        for source, context in (("松本吉朗", "シュラン・オペル"), ("千葉一伸", "アーノルド・ノイマン"), ("千葉一伸", None)):
            with self.assertRaisesRegex(ValueError, "preimage drift"):
                resolve_scoped_translation(self.overrides, "character/408/ACTR", source, "old", context_text=context)

    def test_typo_in_id_cannot_leave_an_unused_correction(self):
        with self.assertRaisesRegex(ValueError, "unused scoped"):
            verify_scoped_translation_coverage(self.overrides, ["character/409/ACTR"])
        verify_scoped_translation_coverage(self.overrides, ["character/408/ACTR"])

    def test_duplicate_and_invalid_hash_are_rejected(self):
        for rows in ([self.row, self.row], [{**self.row, "source_text_sha256": "bad"}]):
            with self.assertRaises(ValueError):
                load_scoped_translations(rows)

    def test_npc_override_preserves_other_titans_entries(self):
        rows = load_scoped_translations([dict(id="display-name/pilot/0796/given",
            source_text_sha256=sha("ティターンズ"), translation="奥古士兵")])
        for index, expected in ((796, "奥古士兵"), (795, "提坦斯")):
            self.assertEqual(resolve_scoped_translation(rows, f"display-name/pilot/{index:04d}/given",
                             "ティターンズ", "提坦斯"), expected)


if __name__ == "__main__":
    unittest.main()
