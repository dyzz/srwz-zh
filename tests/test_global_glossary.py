from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Iterator

from tools.srwz.glossary import (
    GlossaryError,
    apply_glossary_variants,
    global_glossary_by_id,
    load_global_glossary,
)


ROOT = Path(__file__).resolve().parents[1]
GLOSSARY_DIR = ROOT / "corpus/glossary"
ZH_CORPUS = ROOT / "corpus/zh"


def objects(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from objects(child)


class GlobalGlossaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.terms = load_global_glossary(GLOSSARY_DIR)
        cls.by_id = global_glossary_by_id(cls.terms)

    def test_all_components_form_one_conflict_free_registry(self) -> None:
        self.assertGreaterEqual(len(self.terms), 1773)
        self.assertEqual(len(self.terms), len(self.by_id))

        global_variants = [
            term for term in self.terms if term["variant_scope"] == "global"
        ]
        # Building the replacement map detects one deprecated form being
        # assigned to two different canonical terms.
        self.assertEqual(apply_glossary_variants("", global_variants), ("", []))

    def test_duplicate_ids_merge_but_conflicting_translations_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "a.json").write_text(
                json.dumps(
                    {
                        "terms": [
                            {
                                "id": "people/example",
                                "source_terms": ["甲"],
                                "translation": "示例",
                                "status": "proposed",
                                "enforce": True,
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (directory / "b.json").write_text(
                json.dumps(
                    {
                        "terms": [
                            {
                                "id": "people/example",
                                "source_terms": ["乙"],
                                "translation": "示例",
                                "deprecated_translations": ["旧例"],
                                "status": "approved",
                                "enforce": True,
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            merged = load_global_glossary(directory)
            self.assertEqual(len(merged), 1)
            self.assertEqual(merged[0]["source_terms"], ["乙", "甲"])
            self.assertEqual(merged[0]["deprecated_translations"], ["旧例"])
            self.assertTrue(merged[0]["enforce"])

            document = json.loads((directory / "b.json").read_text(encoding="utf-8"))
            document["terms"][0]["translation"] = "冲突"
            (directory / "b.json").write_text(
                json.dumps(document, ensure_ascii=False), encoding="utf-8"
            )
            with self.assertRaisesRegex(
                GlossaryError, "conflicting glossary translation"
            ):
                load_global_glossary(directory)

    def test_every_formal_glossary_reference_resolves(self) -> None:
        missing: list[str] = []
        for path in sorted(ZH_CORPUS.rglob("*.json")):
            document = json.loads(path.read_text(encoding="utf-8"))
            for item in objects(document):
                refs = item.get("glossary_refs")
                if not isinstance(refs, list):
                    continue
                for term_id in refs:
                    if term_id not in self.by_id:
                        missing.append(f"{path.relative_to(ROOT)}:{item.get('id')}:{term_id}")
        self.assertEqual(missing, [])

    def test_approved_enforced_terms_match_every_bound_surface(self) -> None:
        mismatches: list[str] = []
        checked = 0
        for path in sorted(ZH_CORPUS.rglob("*.json")):
            document = json.loads(path.read_text(encoding="utf-8"))
            for item in objects(document):
                refs = item.get("glossary_refs")
                translation = item.get("translation")
                if not isinstance(refs, list) or not isinstance(translation, str):
                    continue
                for term_id in refs:
                    term = self.by_id[term_id]
                    if not term["enforce"]:
                        continue
                    checked += 1
                    canonical = str(term["translation"])
                    compact_translation = translation.replace("\n", "").replace("　", "")
                    if canonical not in compact_translation:
                        mismatches.append(
                            f"{path.relative_to(ROOT)}:{item.get('id')}:"
                            f"{term_id}:{canonical}"
                        )
        self.assertGreater(checked, 300)
        self.assertEqual(mismatches, [])

    def test_selected_release_terms_have_one_canonical_form(self) -> None:
        expected = {
            "organization/emaan": "埃曼",
            "faction/aldébaran": "阿尔德巴朗",
            "unit/g-shadow": "G战影",
            "unit/god-gravion": "神机重力王",
            "people/speaker-58574ffbd89b": "威兹",
            "organization/earth-federation-forces": "地球联邦军",
            "species/scub-coral": "斯卡布珊瑚",
            "unit/xabungle": "萨芬格尔",
            "unit/walker-gallia": "Walker Gallia",
            "concept/contolism": "康提主义",
            "concept/ereism": "地球圣地主义",
            "concept/sideism": "Side国家主义",
        }
        self.assertEqual(
            {term_id: self.by_id[term_id]["translation"] for term_id in expected},
            expected,
        )


if __name__ == "__main__":
    unittest.main()
