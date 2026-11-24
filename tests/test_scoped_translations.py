import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from srwz.scoped_translations import (
    load_line_speaker_name_overrides, load_scoped_translations, load_stage_speaker_name_overrides,
    resolve_scoped_translation,
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


class StageSpeakerNameOverrideTests(unittest.TestCase):
    """Two characters sharing one Japanese speaker name: the shared entry stays, single stages are renamed."""

    def document(self, **override):
        entries = [dict(id="story/002/speaker/005", source_text_sha256=sha("レイ"), translation="雷"),
                   dict(id="story/085/speaker/008", source_text_sha256=sha("レイ"), translation="雷")]
        row = {**dict(id="story/085/speaker/008", source_text_sha256=sha("レイ"), translation="蕾"), **override}
        return dict(entries=entries, stage_name_overrides=[row])

    def test_renames_only_the_listed_stage_speaker(self):
        self.assertEqual(load_stage_speaker_name_overrides(self.document()), {"story/085/speaker/008": "蕾"})
        self.assertEqual(load_stage_speaker_name_overrides(dict(entries=[])), {})

    def test_unknown_entry_changed_source_and_no_op_are_rejected(self):
        for override, message in ((dict(id="story/085/speaker/999"), "unknown stage speaker"),
                                  (dict(id="story/085/condition/01/02"), "unknown stage speaker"),
                                  (dict(source_text_sha256=sha("レイ・ビームス")), "preimage drift"),
                                  (dict(translation="雷"), "changes nothing")):
            with self.assertRaisesRegex(ValueError, message):
                load_stage_speaker_name_overrides(self.document(**override))


    def test_line_overrides_are_keyed_by_dialogue_entry(self):
        row = dict(id="story/148/dialogue/01.23/0009", source_text_sha256=sha("レイ"), translation="蕾")
        self.assertEqual(load_line_speaker_name_overrides(dict(line_name_overrides=[row])),
                         {"story/148/dialogue/01.23/0009": row})
        self.assertEqual(load_line_speaker_name_overrides({}), {})
        with self.assertRaisesRegex(ValueError, "not a dialogue entry"):
            load_line_speaker_name_overrides(dict(line_name_overrides=[{**row, "id": "story/148/speaker/079"}]))


if __name__ == "__main__":
    unittest.main()
