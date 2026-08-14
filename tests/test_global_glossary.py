from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Iterator

from tools.srwz.glossary import (
    GlossaryError,
    apply_glossary_variants,
    deprecated_translation_conflicts,
    global_glossary_by_id,
    load_global_glossary,
    relevant_glossary_terms,
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


def release_strings(value: Any, path: str = "") -> Iterator[tuple[str, str]]:
    """Yield player-facing corpus strings, excluding editorial-only notes."""

    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"note", "notes"}:
                continue
            yield from release_strings(child, f"{path}/{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from release_strings(child, f"{path}/{index}")
    elif isinstance(value, str):
        yield path, value


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

    def test_deprecated_substring_does_not_rewrite_canonical_surface(self) -> None:
        terms = [
            {
                "id": "unit/example",
                "translation": "钢狮子",
                "deprecated_translations": ["钢狮"],
            }
        ]
        self.assertEqual(apply_glossary_variants("钢狮子", terms), ("钢狮子", []))
        self.assertEqual(
            apply_glossary_variants("钢狮与钢狮子", terms),
            ("钢狮子与钢狮子", ["钢狮→钢狮子[unit/example]"]),
        )
        self.assertEqual(deprecated_translation_conflicts("钢狮子", terms), [])
        self.assertEqual(
            deprecated_translation_conflicts("钢狮与钢狮子", terms)[0]["matched"],
            ["钢狮"],
        )

    def test_longer_registered_source_shadows_short_name(self) -> None:
        terms = [
            {
                "id": "people/cielo",
                "source_terms": ["シエロ"],
                "translation": "谢洛",
                "enforce": True,
                "declared_enforce": True,
                "status": "approved",
            },
            {
                "id": "place/del-cielo",
                "source_terms": ["デル・シエロ"],
                "translation": "德尔·谢罗",
                "enforce": True,
                "declared_enforce": True,
                "status": "approved",
            },
        ]
        matches = relevant_glossary_terms("シウダデス・デル・シエロ", terms)
        self.assertEqual([term["id"] for term in matches], ["place/del-cielo"])

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

    def test_malformed_variant_lists_fail_closed(self) -> None:
        cases = (
            ({"source_terms": ["甲", "甲"]}, "duplicate source_terms"),
            (
                {"deprecated_translations": ["旧例", "旧例"]},
                "duplicate deprecated_translations",
            ),
            (
                {"deprecated_translations": ["示例"]},
                "canonical translation is also deprecated",
            ),
        )
        for patch, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                term = {
                    "id": "people/example",
                    "source_terms": ["甲"],
                    "translation": "示例",
                    "deprecated_translations": ["旧例"],
                }
                term.update(patch)
                (directory / "terms.json").write_text(
                    json.dumps({"terms": [term]}, ensure_ascii=False),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(GlossaryError, message):
                    load_global_glossary(directory)

    def test_one_source_form_cannot_have_conflicting_canonical_terms(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "terms.json").write_text(
                json.dumps(
                    {
                        "terms": [
                            {
                                "id": "people/example-a",
                                "source_terms": ["甲"],
                                "translation": "示例甲",
                            },
                            {
                                "id": "people/example-b",
                                "source_terms": ["甲"],
                                "translation": "示例乙",
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(GlossaryError, "conflicting glossary source"):
                load_global_glossary(directory)

    def test_global_deprecated_forms_do_not_leak_into_release_corpus(self) -> None:
        global_terms = [
            term for term in self.terms if term["variant_scope"] == "global"
        ]
        leaks: list[str] = []
        checked = 0
        for path in sorted(ZH_CORPUS.rglob("*.json")):
            document = json.loads(path.read_text(encoding="utf-8"))
            for field_path, value in release_strings(document):
                checked += 1
                compact_value = re.sub(r"[\s　]+", "", value)
                for term in global_terms:
                    for deprecated in term["deprecated_translations"]:
                        compact_deprecated = re.sub(r"[\s　]+", "", deprecated)
                        if compact_deprecated in compact_value:
                            leaks.append(
                                f"{path.relative_to(ROOT)}{field_path}:"
                                f"{term['id']}:{deprecated}"
                            )
        self.assertGreater(checked, 120_000)
        self.assertEqual(leaks, [])

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

    def test_world_history_scroll_matches_every_relevant_global_term(self) -> None:
        summary = json.loads(
            (ZH_CORPUS / "summary.json").read_text(encoding="utf-8")
        )
        formal_refs = {
            term_id
            for entry in summary["entries"]
            for term_id in entry.get("glossary_refs", [])
        }
        term_ids = sorted(
            str(term["id"])
            for term in self.terms
            if "summary" in term["domains"]
            or term["id"] in formal_refs
            or term["variant_scope"] == "global"
        )
        with tempfile.TemporaryDirectory() as temporary:
            report_path = Path(temporary) / "summary-glossary-audit.json"
            command = [
                sys.executable,
                str(ROOT / "tools/audit_source_bound_glossary.py"),
                "--surface",
                "summary",
                "--report",
                str(report_path),
                "--fail-on-mismatch",
            ]
            for term_id in term_ids:
                command.extend(("--term-id", term_id))
            result = subprocess.run(
                command,
                cwd=ROOT,
                env={**os.environ, "PYTHONPATH": str(ROOT / "tools")},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(report["surfaces"], ["summary"])
        self.assertEqual(report["source_occurrence_count"], 75)
        self.assertEqual(report["mismatch_count"], 0)

    def test_selected_release_terms_have_one_canonical_form(self) -> None:
        expected = {
            "organization/emaan": "埃曼",
            "organization/gekkostate": "月光洲",
            "organization/titans": "提坦斯",
            "organization/aeug": "奥古",
            "activity/lifting": "滑空",
            "faction/aldébaran": "阿尔德巴朗",
            "faction/gaizok": "盖佐克",
            "unit/g-shadow": "G战影",
            "unit/god-gravion": "神机超重神",
            "unit/gran-diva": "超重机组",
            "unit/proto-gran-diva": "原型超重机组",
            "unit/geo-mirage": "Geo幻象",
            "people/speaker-58574ffbd89b": "威兹",
            "people/speaker-22359c86b24b": "西利乌斯",
            "organization/earth-federation-forces": "地球联邦军",
            "place/unious-seven": "尤尼乌斯7",
            "species/scub-coral": "珊瑚岩",
            "unit/naikick": "奈基克",
            "unit/xabungle": "萨芬格尔",
            "unit/walker-gallia": "沃卡加利亚",
            "concept/contolism": "康提主义",
            "concept/ereism": "地球圣地主义",
            "concept/sideism": "Side国家主义",
            "concept/sphere": "珠玉",
            "energy/dimensional-power": "次元力",
            "concept/origin-law": "源理之力",
            "concept/great-power": "伟大之力",
            "technology/dimensional-boundary-line": "次元边界线",
            "technology/spacetime-oscillation-bomb": "时空震动弹",
            "technology/great-singularity": "大奇点",
            "technology/singularity": "奇点",
            "system/un-network": "UN",
        }
        self.assertEqual(
            {term_id: self.by_id[term_id]["translation"] for term_id in expected},
            expected,
        )

    def test_reported_names_match_every_japanese_source_occurrence(self) -> None:
        term_ids = [
            "organization/gekkostate",
            "organization/titans",
            "organization/aeug",
            "faction/gaizok",
            "unit/freedom-gundam",
            "unit/freeden",
            "unit/strike-freedom-gundam",
            "people/speaker-9f0da37da623",
            "people/speaker-b3a6e71cada9",
            "people/moondoggie-short",
            "people/speaker-e00210e47303",
        ]
        with tempfile.TemporaryDirectory() as temporary:
            report_path = Path(temporary) / "source-bound-audit.json"
            command = [
                sys.executable,
                str(ROOT / "tools/audit_source_bound_glossary.py"),
                "--report",
                str(report_path),
                "--fail-on-mismatch",
            ]
            for term_id in term_ids:
                command.extend(("--term-id", term_id))
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(ROOT / "tools")
            result = subprocess.run(
                command,
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["mismatch_count"], 0)
        self.assertEqual(
            report["source_occurrences"],
            {
                "organization/gekkostate": 221,
                "organization/titans": 218,
                "organization/aeug": 253,
                "faction/gaizok": 191,
                "unit/freedom-gundam": 153,
                "unit/freeden": 204,
                "unit/strike-freedom-gundam": 2,
                "people/speaker-9f0da37da623": 154,
                "people/speaker-b3a6e71cada9": 4,
                "people/moondoggie-short": 46,
                "people/speaker-e00210e47303": 197,
            },
        )

    def test_original_setting_terms_match_every_japanese_source_occurrence(self) -> None:
        expected = {
            "concept/sphere": 120,
            "energy/dimensional-power": 107,
            "concept/origin-law": 26,
            "concept/great-power": 95,
            "concept/taiji": 98,
            "technology/dimensional-boundary-line": 88,
            "technology/spacetime-oscillation-bomb": 64,
            "technology/great-singularity": 97,
            "technology/singularity": 261,
            "technology/dimensional-boundary": 42,
            "system/un-network": 343,
        }
        with tempfile.TemporaryDirectory() as temporary:
            report_path = Path(temporary) / "original-setting-audit.json"
            command = [
                sys.executable,
                str(ROOT / "tools/audit_source_bound_glossary.py"),
                "--report",
                str(report_path),
                "--fail-on-mismatch",
            ]
            for term_id in expected:
                command.extend(("--term-id", term_id))
            result = subprocess.run(
                command,
                cwd=ROOT,
                env={**os.environ, "PYTHONPATH": str(ROOT / "tools")},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(report["mismatch_count"], 0)
        self.assertEqual(report["source_occurrences"], expected)


if __name__ == "__main__":
    unittest.main()
