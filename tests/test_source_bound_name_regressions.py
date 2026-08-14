import json
import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from tools.audit_source_bound_glossary import (
    SourceTranslation,
    audit_source_terms,
    load_source_translations,
)
from tools.srwz.glossary import load_global_glossary


def glossary_term(path: str, term_id: str) -> dict:
    document = json.loads((ROOT / path).read_text(encoding="utf-8"))
    return next(term for term in document["terms"] if term["id"] == term_id)


class SourceBoundNameRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = load_source_translations(ROOT)

    def test_confirmed_person_names_are_source_bound(self) -> None:
        expected_occurrences = {
            "people/speaker-e00210e47303": 197,  # エイジ -> 英司
            "people/speaker-0fb8d52aeaf0": 83,  # ガットラー -> 加特勒
            "people/speaker-c12dfb53f28b": 134,  # アフロディア -> 阿芙罗蒂亚
            "people/speaker-cbd92fab5f0b": 41,  # クインシュタイン -> 奎因斯坦
            "people/speaker-39bb8bf5e8f1": 35,  # ギャバン -> 嘉班
            "people/speaker-71fbb7dba7d3": 256,  # シロッコ -> 西罗克
            "people/speaker-d142d771217a": 13,  # ディアッカ -> 迪安卡
            "people/speaker-24b19e20c0e0": 4,  # シンゴ -> 新吾
            "people/speaker-5cf2a20e0254": 8,  # シド -> 希德
            "people/speaker-6b04fe4b92a7": 1,  # ダンケル -> 邓克尔
            "people/speaker-ed4360aca4c4": 10,  # マユ -> 玛尤
            "people/speaker-9af21164f24e": 30,  # さやか -> 沙也加
            "people/speaker-9cbe65863d05": 3,  # チュイル -> 裘露
            "people/speaker-0a8ee4e9b797": 18,  # テテス -> 特泰丝
        }
        for term_id, expected in expected_occurrences.items():
            with self.subTest(term_id=term_id):
                term = glossary_term(
                    "corpus/glossary/story-speakers-v1.json",
                    term_id,
                )
                report = audit_source_terms(self.rows, [term])
                self.assertEqual(
                    report["source_occurrences"],
                    {term_id: expected},
                )
                self.assertEqual(report["mismatches"], [])

    def test_gravion_terms_match_japanese_source_context(self) -> None:
        by_id = {
            term["id"]: term
            for term in load_global_glossary(ROOT / "corpus/glossary")
        }
        term_ids = [
            "episode/gravion-12",
            "faction/zeravire",
            "organization/gran-knights",
            "people/speaker-389b01366661",
            "technology/ergo-storm",
            "unit/god-gravion",
            "unit/god-sigma-gravion",
            "unit/gran-diva",
            "unit/proto-gran-diva",
            "unit/sol-grandiva",
            "unit/geo-calibur",
            "unit/geo-stinger",
            "unit/geo-javelin",
            "unit/geo-mirage",
            "unit/soldier-zeravire",
            "unit/ultimate-gravion",
            "weapon/0566",
            "weapon/0570",
            "weapon/0571",
            "weapon/0572",
            "weapon/0575",
            "weapon/0578",
            "weapon/0584",
            "weapon/graviton-viper",
        ]
        report = audit_source_terms(
            self.rows,
            [by_id[term_id] for term_id in term_ids],
        )
        self.assertGreater(report["source_occurrence_count"], 0)
        self.assertEqual(report["mismatches"], [])

    def test_longer_source_terms_shadow_short_kana_names(self) -> None:
        rows = [
            SourceTranslation("story", "ordinary", "ささやかな礼", "微薄谢礼", ()),
            SourceTranslation("story", "weapon", "マリンミサイル", "海洋导弹", ()),
            SourceTranslation("story", "person", "マリン！", "马林！", ()),
            SourceTranslation("battle", "anemone", "アネモネ！", "安妮莫奈！", ()),
            SourceTranslation("story", "fan", "ミイヤのファン", "米娅的粉丝", ()),
            SourceTranslation("story", "skyfish", "スカイフィッシュ", "天鱼", ()),
            SourceTranslation("story", "mayu", "マユーッ！！", "玛尤——！！", ()),
        ]
        terms = [
            {
                "id": "people/sayaka",
                "source_terms": ["さやか"],
                "translation": "沙也加",
                "domains": ["story"],
            },
            {
                "id": "people/marin",
                "source_terms": ["マリン"],
                "translation": "马林",
                "domains": ["story"],
            },
            {
                "id": "weapon/marine-missile",
                "source_terms": ["マリンミサイル"],
                "translation": "海洋导弹",
                "domains": ["story"],
            },
            {
                "id": "unit/nemo",
                "source_terms": ["ネモ"],
                "translation": "雷姆",
                "domains": ["battle"],
            },
            {
                "id": "people/anemone",
                "source_terms": ["アネモネ"],
                "translation": "安妮莫奈",
                "domains": ["story"],
            },
            {
                "id": "people/fa",
                "source_terms": ["ファ"],
                "translation": "花",
                "domains": ["story"],
            },
            {
                "id": "people/kai",
                "source_terms": ["カイ"],
                "translation": "凯",
                "domains": ["story"],
            },
            {
                "id": "people/mayu",
                "source_terms": ["マユ"],
                "translation": "玛尤",
                "domains": ["story"],
            },
        ]
        report = audit_source_terms(rows, terms)
        self.assertEqual(
            report["source_occurrences"],
            {
                "people/sayaka": 0,
                "people/marin": 1,
                "weapon/marine-missile": 1,
                "unit/nemo": 0,
                "people/anemone": 0,
                "people/fa": 0,
                "people/kai": 0,
                "people/mayu": 1,
            },
        )
        self.assertEqual(report["mismatches"], [])

    def test_deprecated_surface_is_not_hidden_by_canonical_in_same_row(self) -> None:
        rows = [
            SourceTranslation(
                "story",
                "mixed",
                "スカブコーラルとスカブ",
                "斯卡布珊瑚与斯库布",
                (),
            )
        ]
        terms = [
            {
                "id": "species/scub-coral",
                "source_terms": ["スカブコーラル"],
                "translation": "斯卡布珊瑚",
                "deprecated_translations": ["斯库布珊瑚"],
                "domains": ["story"],
            },
            {
                "id": "species/scub-short",
                "source_terms": ["スカブ"],
                "translation": "斯卡布",
                "deprecated_translations": ["斯库布"],
                "domains": ["story"],
            },
        ]
        report = audit_source_terms(rows, terms)
        self.assertEqual(report["source_occurrences"], {
            "species/scub-coral": 1,
            "species/scub-short": 1,
        })
        self.assertEqual(report["mismatch_count"], 1)
        self.assertEqual(
            report["mismatches"][0]["deprecated_translation_hits"],
            ["斯库布"],
        )

    def test_setsuko_only_appears_in_setsuko_source_context(self) -> None:
        term = glossary_term(
            "corpus/glossary/terms-v1.json",
            "people/setsuko",
        )
        report = audit_source_terms(self.rows, [term])
        self.assertEqual(report["source_occurrences"], {term["id"]: 25})
        self.assertEqual(report["mismatches"], [])

        unbound = [
            row.entry_id
            for row in self.rows
            if "节子" in re.sub(r"[\s　]+", "", row.translation)
            and "セツコ" not in row.source_text
        ]
        self.assertEqual(unbound, [])

    def test_sirius_name_is_not_translated_as_the_star(self) -> None:
        term = glossary_term(
            "corpus/glossary/global-variants-v1.json",
            "people/speaker-22359c86b24b",
        )
        self.assertEqual(term["translation"], "西利乌斯")
        self.assertEqual(
            term["deprecated_translations"],
            ["西里乌斯", "天狼星", "天狼"],
        )
        report = audit_source_terms(self.rows, [term])
        self.assertEqual(
            report["source_occurrences"],
            {term["id"]: 255},
        )
        self.assertEqual(report["mismatches"], [])

    def test_sirius_deprecated_names_do_not_leak_into_release_corpus(self) -> None:
        deprecated = ("西里乌斯", "天狼星", "天狼")
        leaks: list[str] = []

        def strings(value: object, path: str = ""):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key in {"note", "notes"}:
                        continue
                    yield from strings(child, f"{path}/{key}")
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    yield from strings(child, f"{path}/{index}")
            elif isinstance(value, str):
                yield path, value

        for corpus_path in sorted((ROOT / "corpus/zh").rglob("*.json")):
            document = json.loads(corpus_path.read_text(encoding="utf-8"))
            for field_path, value in strings(document):
                for old_name in deprecated:
                    if old_name in value:
                        leaks.append(
                            f"{corpus_path.relative_to(ROOT)}{field_path}:{old_name}"
                        )
        self.assertEqual(leaks, [])

    def test_genki_name_is_distinguished_from_the_common_word(self) -> None:
        term = glossary_term(
            "corpus/glossary/global-variants-v1.json",
            "people/speaker-7fc6e83611c6",
        )
        report = audit_source_terms(self.rows, [term])
        self.assertEqual(report["source_occurrences"], {term["id"]: 101})
        self.assertEqual(report["mismatches"], [])

        bound_rows = [
            row
            for row in self.rows
            if row.surface == "story" and "元気" in row.source_text
        ]
        self.assertEqual(len(bound_rows), 101)
        self.assertEqual(
            sum(term["id"] in row.glossary_exceptions for row in bound_rows),
            99,
        )

    def test_king_gainer_official_setting_terms_are_source_bound(self) -> None:
        term_ids = {
            "ability/overskill",
            "event/exodus",
            "organization/london-ima",
            "organization/saint-regan",
            "organization/siberian-railway",
            "organization/siberian-railway-full",
            "organization/siberian-railway-guard",
            "organization/siberian-railway-guard-short",
            "place/domepolis",
            "place/yapans-ceiling",
            "technology/photon-mat",
            "technology/photon-mat-ring",
            "unit/black-domi",
            "unit/emperanza",
            "unit/gachiko",
            "unit/overdevil",
            "unit/overman",
            "unit/panther",
            "unit/silhouette-engine",
            "unit/silhouette-machine",
            "unit/silhouette-mammoth",
            "weapon/panther-shoot",
        }
        terms = [
            term
            for term in load_global_glossary(ROOT / "corpus/glossary")
            if term["id"] in term_ids
        ]
        self.assertEqual({term["id"] for term in terms}, term_ids)

        report = audit_source_terms(self.rows, terms)
        self.assertEqual(report["mismatches"], [])
        self.assertEqual(report["source_occurrence_count"], 1530)
        self.assertTrue(all(report["source_occurrences"].values()))

    def test_all_approved_people_and_units_match_battle_source(self) -> None:
        terms = []
        for term in load_global_glossary(ROOT / "corpus/glossary"):
            if (
                term.get("status") != "approved"
                or term.get("category") not in {"people", "unit"}
            ):
                continue
            battle_term = dict(term)
            battle_term["domains"] = ["battle"]
            terms.append(battle_term)
        battle_rows = [row for row in self.rows if row.surface == "battle"]
        report = audit_source_terms(battle_rows, terms)
        self.assertEqual(report["mismatches"], [])


if __name__ == "__main__":
    unittest.main()
