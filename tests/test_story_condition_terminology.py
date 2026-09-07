from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from tools.srwz.glossary import (
    deprecated_translation_conflicts,
    global_glossary_by_id,
    load_global_glossary,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class StoryConditionTerminologyTest(unittest.TestCase):
    def test_retired_aquarion_name_is_absent_from_chinese_corpus(self) -> None:
        def strings(value):
            if isinstance(value, str):
                yield value
            elif isinstance(value, dict):
                for child in value.values():
                    yield from strings(child)
            elif isinstance(value, list):
                for child in value:
                    yield from strings(child)

        for path in sorted((PROJECT_ROOT / "corpus/zh").rglob("*.json")):
            with self.subTest(path=str(path.relative_to(PROJECT_ROOT))):
                document = json.loads(path.read_text(encoding="utf-8"))
                for value in strings(document):
                    compact = re.sub(r"\\n|\s", "", value)
                    self.assertNotIn("亚库艾里翁", compact)

    def test_conditions_follow_current_approved_terms(self) -> None:
        terms = global_glossary_by_id(
            load_global_glossary(PROJECT_ROOT / "corpus/glossary")
        )
        document = json.loads(
            (PROJECT_ROOT / "corpus/zh/story-conditions.json").read_text(
                encoding="utf-8"
            )
        )
        for entry in document["entries"]:
            with self.subTest(entry_id=entry["id"]):
                refs = entry["glossary_refs"]
                self.assertFalse(set(refs) - set(terms))
                approved = [terms[ref] for ref in refs if terms[ref]["enforce"]]
                text = "".join(entry["translation"].split())
                self.assertEqual(deprecated_translation_conflicts(text, approved), [])

                # Each distinct bound name needs its own occurrence.  Otherwise
                # "Aquarion或强攻型亚库艾里翁" falsely satisfies both unit names
                # because the shorter canonical name occurs inside the longer.
                canonicals = {
                    "".join(str(term["translation"]).split()) for term in approved
                }
                for canonical in sorted(
                    canonicals, key=lambda value: (-len(value), value)
                ):
                    self.assertIn(canonical, text)
                    text = text.replace(canonical, " " * len(canonical), 1)


if __name__ == "__main__":
    unittest.main()
