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

    def test_xabungle_terms_match_japanese_source_context(self) -> None:
        by_id = {
            term["id"]: term
            for term in load_global_glossary(ROOT / "corpus/glossary")
        }
        expected_occurrences = {
            "people/civilian": 15,
            "unit/walker-gallia": 17,
            "unit/iron-gear": 236,
            "unit/brockary": 4,
            "organization/sand-rat": 12,
            "people/geraba": 17,
        }
        report = audit_source_terms(
            self.rows,
            [by_id[term_id] for term_id in expected_occurrences],
        )
        self.assertEqual(report["source_occurrences"], expected_occurrences)
        self.assertEqual(report["mismatches"], [])

    def test_xabungle_speaker_and_condition_surfaces_use_geraba(self) -> None:
        for relative_path in (
            "corpus/zh/story-speakers.json",
            "corpus/zh/story-conditions.json",
        ):
            document = json.loads((ROOT / relative_path).read_text(encoding="utf-8"))
            bound = [
                entry
                for entry in document["entries"]
                if "people/geraba" in entry.get("glossary_refs", [])
            ]
            self.assertTrue(bound, relative_path)
            self.assertTrue(
                all("格拉巴" in entry["translation"] for entry in bound),
                relative_path,
            )
            self.assertTrue(
                all("杰拉巴" not in entry["translation"] for entry in bound),
                relative_path,
            )

    def test_gundam_x_terms_match_japanese_source_context(self) -> None:
        by_id = {
            term["id"]: term
            for term in load_global_glossary(ROOT / "corpus/glossary")
        }
        expected_occurrences = {
            "people/sara-tyrell": 0,
            "people/tiffa-adill": 46,
            "people/jamil-neate": 36,
            "people/witz-sou": 0,
            "people/roybea-loy": 0,
            "people/kid-salsamille": 2,
            "people/shagia-frost": 12,
            "people/shingo-mori": 0,
            "people/pala-sys": 4,
            "people/lancerow-darwell": 8,
            "people/katokk-alzamille": 0,
            "people/seidel-rasso": 1,
            "people/carris-nautilus": 3,
            "people/lucille-lilliant": 4,
            "people/abel-bauer": 2,
            "unit/gundam-x-divider": 0,
            "unit/gundam-airmaster": 0,
            "unit/gundam-airmaster-burst": 0,
            "unit/gundam-leopard": 0,
            "unit/gundam-leopard-destroy": 0,
            "unit/gundam-virsago-chest-break": 0,
            "unit/daughtress-neo": 0,
            "unit/clouda": 0,
            "unit/bertigo": 0,
            "unit/gundam-double-x-spoken": 4,
            "unit/g-falcon": 16,
            "unit/airmaster-short": 7,
            "unit/leopard-short": 3,
            "unit/virsago-short": 4,
            "unit/ashtaron-hc": 0,
            "unit/gadiel": 0,
        }
        report = audit_source_terms(
            self.rows,
            [by_id[term_id] for term_id in expected_occurrences],
        )
        self.assertEqual(report["source_occurrences"], expected_occurrences)
        self.assertEqual(report["mismatches"], [])

    def test_gundam_x_condition_uses_clouda(self) -> None:
        document = json.loads(
            (ROOT / "corpus/zh/story-conditions.json").read_text(encoding="utf-8")
        )
        bound = [
            entry
            for entry in document["entries"]
            if "unit/clouda" in entry.get("glossary_refs", [])
        ]
        self.assertTrue(bound)
        self.assertTrue(all("克鲁达" in entry["translation"] for entry in bound))
        self.assertTrue(all("克劳达" not in entry["translation"] for entry in bound))

    def test_gundam_x_pilot_name_components_follow_reviewed_full_names(self) -> None:
        document = json.loads(
            (ROOT / "corpus/zh/menu/remaining-ui.json").read_text(encoding="utf-8")
        )
        names = document["display_names_by_source_text"]
        expected = {
            "アディール": "阿迪尔",
            "ニート": "尼特",
            "タイレル": "泰雷尔",
            "モリ": "森",
            "スー": "苏",
            "ロイ": "罗伊",
            "サルサミル": "萨尔萨米尔",
            "シス": "西斯",
            "フロスト": "弗罗斯特",
            "ダーウェル": "达威尔",
            "アルザミール": "阿尔扎米尔",
            "ラッソ": "拉索",
            "ノーティラス": "诺提拉斯",
            "リリアント": "莉莉安特",
            "バウアー": "鲍尔",
        }
        self.assertEqual({source: names[source] for source in expected}, expected)

    def test_big_o_terms_match_japanese_source_context(self) -> None:
        by_id = {
            term["id"]: term
            for term in load_global_glossary(ROOT / "corpus/glossary")
        }
        expected_occurrences = {
            "concept/dominus": 24,
            "concept/paradigm-shift": 1,
            "organization/paradigm-short": 20,
            "place/paradigm-city": 173,
            "organization/paradigm-corporation": 38,
            "people/schwarzwald-full": 23,
            "unit/archetype": 8,
            "unit/megadeus": 59,
            "unit/prairie-dog": 1,
            "unit/big-o": 95,
            "unit/big-duo": 33,
            "unit/big-duo-inferno": 0,
            "unit/big-fau": 12,
            "unit/the-big": 16,
        }
        report = audit_source_terms(
            self.rows,
            [by_id[term_id] for term_id in expected_occurrences],
        )
        self.assertEqual(report["source_occurrences"], expected_occurrences)
        self.assertEqual(report["mismatches"], [])

    def test_zeta_and_chars_counterattack_terms_match_japanese_source(self) -> None:
        by_id = {
            term["id"]: term
            for term in load_global_glossary(ROOT / "corpus/glossary")
        }
        expected_occurrences = {
            "unit/rick-dias": 7,
            "unit/re-gz": 6,
            "people/fa-yuiry-full": 4,
            "people/reccoa-londe-full": 22,
            "people/four-murasame-full": 7,
            "people/bran-blutarch-full": 0,
            "people/rosamia-badam-full": 0,
            "people/ben-wood-full": 0,
            "people/henken-bekkener-full": 0,
            "people/mouar-pharaoh-full": 0,
            "people/blex-forer-full": 1,
            "people/gady-kinsey-full": 0,
            "technology/psycommu": 14,
            "weapon/0271": 10,
            "ability/psycho-frame": 10,
        }
        report = audit_source_terms(
            self.rows,
            [by_id[term_id] for term_id in expected_occurrences],
        )
        self.assertEqual(report["source_occurrences"], expected_occurrences)
        self.assertEqual(report["mismatches"], [])

    def test_seed_destiny_terms_match_japanese_source_context(self) -> None:
        by_id = {
            term["id"]: term
            for term in load_global_glossary(ROOT / "corpus/glossary")
        }
        expected_occurrences = {
            "unit/force-impulse-gundam": 0,
            "unit/akatsuki-gundam": 3,
            "unit/minerva": 447,
            "unit/girty-lue": 3,
            "unit/core-splendor": 5,
            "people/lunamaria": 68,
            "people/stella-loussier": 2,
        }
        report = audit_source_terms(
            self.rows,
            [by_id[term_id] for term_id in expected_occurrences],
        )
        self.assertEqual(report["source_occurrences"], expected_occurrences)
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
