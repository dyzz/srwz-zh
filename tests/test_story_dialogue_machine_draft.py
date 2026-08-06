import tempfile
import unittest
from pathlib import Path

from tools.build_story_dialogue_machine_draft import (
    DEFAULT_ENGLISH_ALIASES,
    _load_english_aliases,
    _load_upstream_story,
    _normalize_translation,
    _protect_source,
    _restore_dialogue_quote_shape,
    _restore_protected,
)


class StoryDialogueMachineDraftTests(unittest.TestCase):
    def test_english_alias_glossary_is_data_driven_and_case_sensitive(self):
        aliases = _load_english_aliases(DEFAULT_ENGLISH_ALIASES)
        self.assertIn(
            ("Gunleon", "钢狮", "unit/gunleon-en"),
            aliases,
        )
        self.assertIn(
            ("The Crasher", "破坏者", "people/the-crasher-en"),
            aliases,
        )
        protected_source, protected, term_ids = _protect_source(
            "Gunleon, but not gunleon.",
            (),
            extra_terms=aliases,
        )
        self.assertNotIn("Gunleon", protected_source)
        self.assertIn("gunleon", protected_source)
        self.assertIn("unit/gunleon-en", term_ids)
        restored, missing = _restore_protected(protected_source, protected)
        self.assertEqual(missing, ())
        self.assertEqual(restored, "钢狮, but not gunleon.")

    def test_upstream_xml_joins_pointer_and_speaker_alias(self):
        xml = """<ScenarioText>
          <Speakers><Entry><EnglishText>Geraba</EnglishText><Id>1</Id></Entry></Speakers>
          <Strings><Entry><PointerOffset>1424</PointerOffset>
            <EnglishText>Huh...</EnglishText></Entry></Strings>
        </ScenarioText>"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "018.xml"
            path.write_text(xml, encoding="utf-8")
            document = _load_upstream_story(path)
        self.assertEqual(
            document["english_by_pointer"],
            {1424: "Huh..."},
        )
        self.assertEqual(
            document["english_speakers"],
            {1: "Geraba"},
        )

    def test_english_alias_and_runtime_token_are_restored(self):
        protected_source, protected, term_ids = _protect_source(
            "Geraba uses $n.",
            (),
            extra_terms=(("Geraba", "杰拉巴", "speaker/001"),),
        )
        self.assertNotIn("Geraba", protected_source)
        self.assertNotIn("$n", protected_source)
        self.assertEqual(term_ids, ("speaker/001",))
        restored, missing = _restore_protected(
            protected_source,
            protected,
        )
        self.assertEqual(missing, ())
        self.assertEqual(restored, "杰拉巴 uses $n.")

    def test_dialogue_quote_shape_is_preserved_without_inventing_quotes(self):
        self.assertEqual(
            _restore_dialogue_quote_shape("「あれ…」", "咦……"),
            "“咦……”",
        )
        self.assertEqual(
            _restore_dialogue_quote_shape("あれ…", "咦……"),
            "咦……",
        )

    def test_normalization_removes_alias_spacing_but_keeps_latin_word_spacing(self):
        self.assertEqual(
            _normalize_translation("“这是 钢狮 ！”\n　与 Beater Service 一起"),
            "“这是钢狮！”\n　与 Beater Service 一起",
        )


if __name__ == "__main__":
    unittest.main()
