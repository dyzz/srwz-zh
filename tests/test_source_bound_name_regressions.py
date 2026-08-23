# ruff: noqa: E402
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

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
            "people/speaker-0fb8d52aeaf0": 120,  # ガットラー -> 加特勒
            "people/speaker-c12dfb53f28b": 160,  # アフロディア -> 阿芙罗蒂亚
            "people/speaker-cbd92fab5f0b": 43,  # クインシュタイン -> 奎因斯坦
            "people/speaker-39bb8bf5e8f1": 35,  # ギャバン -> 嘉班
            "people/speaker-71fbb7dba7d3": 256,  # シロッコ -> 西罗克
            "people/speaker-d142d771217a": 13,  # ディアッカ -> 迪安卡
            "people/speaker-24b19e20c0e0": 4,  # シンゴ -> 新吾
            "people/speaker-5cf2a20e0254": 10,  # シド -> 希德
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
            "unit/minerva": 448,
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

    def test_mazinger_series_terms_match_japanese_source_context(self) -> None:
        by_id = {
            term["id"]: term
            for term in load_global_glossary(ROOT / "corpus/glossary")
        }
        expected_occurrences = {
            "organization/mycenae-empire": 1,
            "organization/mycenae-short": 3,
            "organization/space-science-laboratory": 5,
            "organization/vega-alliance-force": 44,
            "people/lady-gandal": 4,
            "people/speaker-052cda3cc4a0": 3,
            "people/speaker-0b7fc6a4043e": 2,
            "people/speaker-3484aadc8637": 0,
            "people/speaker-52bd0a2936b4": 228,
            "people/speaker-9af21164f24e": 30,
            "people/speaker-ad9d3832188b": 44,
            "people/speaker-b85bd152a7ad": 59,
            "people/speaker-c76445843ed2": 27,
            "people/speaker-cb99f5c6f258": 4,
            "place/fleed-planet": 42,
            "place/skull-moon-base": 43,
            "unit/boss-borot": 3,
            "unit/dianan-a": 8,
            "unit/double-spazer": 7,
            "unit/drill-spazer": 2,
            "unit/great-mazinger": 11,
            "unit/grendizer": 43,
            "unit/marine-spazer": 1,
            "unit/mazinger-z": 31,
            "unit/midifo": 4,
            "unit/saucer-beast": 5,
            "unit/saucer-beast-gorgor": 0,
            "unit/spazer": 6,
            "unit/tfo": 8,
            "unit/vega-beast": 4,
            "unit/vega-beast-guragura": 1,
            "unit/venus-a": 1,
            "unit/venus-short": 3,
        }
        report = audit_source_terms(
            self.rows,
            [by_id[term_id] for term_id in expected_occurrences],
        )
        self.assertEqual(report["source_occurrences"], expected_occurrences)
        self.assertEqual(report["mismatches"], [])

    def test_generic_boss_meanings_do_not_use_the_character_name(self) -> None:
        boss_term_id = "people/speaker-ad9d3832188b"
        expected = {
            "story/024/dialogue/01.16/0000":
                "“老大，不行了！机体撑不住了！！”",
            "story/024/dialogue/02.02/0022": "“抱歉了，小姐。要恨就恨你的老板吧。”",
            "story/024/dialogue/02.02/0029":
                "“可、可恶！老大说要小心，就是指这个吗！”",
            "story/024/dialogue/02.02/0234": "“抱歉了，小姐。要恨就恨你的老板吧。”",
            "story/024/dialogue/02.02/0241":
                "“可、可恶！老大说要小心，就是指这个吗！”",
            "story/034/dialogue/01.07/0004": (
                "“一般来说，在这种情况出现的敌人都是\n"
                "　中BOSS……你看！设计也不一样！”"
            ),
            "story/132/dialogue/01.05/0000": (
                "“敌方头目都到齐了吗……！\n　终于到决战时刻了！”"
            ),
            "story/132/dialogue/01.06/0000": (
                "“敌方头目都到齐了吗……！\n　终于到决战时刻了！”"
            ),
            "story/132/dialogue/01.50/0000": (
                "“放马过来吧，大BOSS！\n"
                "　敲碎你的脑袋，结束这场战斗！！”"
            ),
        }
        exceptions = {
            row.entry_id: row.translation
            for row in self.rows
            if boss_term_id in row.glossary_exceptions
        }
        self.assertEqual(exceptions, expected)
        self.assertTrue(all("波士" not in text for text in exceptions.values()))

    def test_accelerator_is_distinguished_from_axel_thurston(self) -> None:
        person_rows = {
            row.entry_id: row.translation
            for row in self.rows
            if "アクセル" in row.source_text and row.surface == "story"
        }
        accelerator_rows = {
            row.entry_id: row.translation
            for row in self.rows
            if "アクセル" in row.source_text and row.surface == "battle"
        }
        self.assertEqual(len(person_rows), 13)
        self.assertTrue(all("阿克塞尔" in text for text in person_rows.values()))
        self.assertEqual(len(accelerator_rows), 5)
        self.assertTrue(all("油门" in text for text in accelerator_rows.values()))
        self.assertTrue(all("阿克塞尔" not in text for text in accelerator_rows.values()))

    def test_bakana_reactions_are_not_translated_as_insults(self) -> None:
        rows = {row.entry_id: row for row in self.rows}
        reaction_ids = {
            "story/031/dialogue/01.28/0000",
            "story/047/dialogue/02.03/0021",
            "story/072/dialogue/01.21/0000",
            "story/125/dialogue/01.05/0000",
            "story/127/dialogue/01.43/0018",
            "story/127/dialogue/01.68/0000",
            "story/131/dialogue/01.37/0001",
            "story/132/dialogue/02.02/0154",
            "story/137/dialogue/01.21/0002",
            "story/139/dialogue/01.44/0002",
            "story/139/dialogue/01.74/0020",
            "story/140/dialogue/01.12/0000",
            "story/140/dialogue/01.15/0012",
            "story/140/dialogue/01.25/0001",
            "story/143/dialogue/01.17/0000",
            "story/143/dialogue/01.28/0000",
            "story/148/dialogue/01.17/0000",
            "story/148/dialogue/01.31/0000",
            "story/149/dialogue/01.22/0000",
            "battle:03892",
            "battle:06985",
            "battle:07158",
            "battle:09222",
            "battle:15670",
            "battle:15800",
            "battle:23319",
            "battle:24654",
            "battle:25509",
            "battle:25638",
        }
        for entry_id in reaction_ids:
            with self.subTest(entry_id=entry_id):
                translation = rows[entry_id].translation
                self.assertNotRegex(translation, r"愚蠢|蠢货|笨蛋|胡说")
                self.assertRegex(translation, r"不可能|怎么可能|开什么玩笑")

        literal_foolishness_ids = {
            "story/056/dialogue/01.18/0006",
            "story/056/dialogue/01.25/0000",
            "battle:04491",
            "battle:08706",
        }
        for entry_id in literal_foolishness_ids:
            with self.subTest(entry_id=entry_id):
                self.assertRegex(rows[entry_id].translation, r"愚蠢|蠢事")

    def test_reported_subject_and_object_drift_stays_fixed(self) -> None:
        rows = {row.entry_id: row.translation for row in self.rows}
        self.assertEqual(
            rows["story/022/dialogue/01.32/0000"],
            "“奥尔森，我启动了时空震动弹！\n"
            "　与其送给大西洋联邦，不如炸掉轨道电梯！”",
        )
        self.assertEqual(rows["battle:23419"], "“斗牙！从正面劈了他！”")
        self.assertEqual(
            rows["story/091/dialogue/02.01/0008"],
            "“可是，小纯……你要输了。”",
        )

    def test_issue_040_and_041_reported_wording_stays_fixed(self) -> None:
        rows = {row.entry_id: row.translation for row in self.rows}
        self.assertEqual(
            rows["story/076/dialogue/01.31/0000"],
            "“这种大家伙，\n　我跟陆行舰交手时\n　就已经打惯了！”",
        )
        self.assertEqual(rows["battle:21009"], "“站那儿别动！”")

    def test_issue_042_reported_wording_stays_fixed(self) -> None:
        rows = {row.entry_id: row.translation for row in self.rows}
        expected = {
            "story/073/dialogue/01.08/0000": (
                "“居然叫‘空停’，真没劲。\n　军人果然都是笨蛋吧？”"
            ),
            "battle:01683": "“把能用的全灌进去吧！”",
            "battle:02475": "“不管从哪儿来，尽管放马过来！”",
            "story/075/dialogue/02.02/0105": (
                "“在其他世界也做过类似的事。\n"
                "　旧地球联邦的强化人，\n"
                "　地球联合的扩展人……”"
            ),
            "battle:21010": "“我已经不是小鬼了！\\n　看我的！”",
            "battle:09061": "“你也是第15年的亡灵吗！”",
            "story/076/dialogue/01.16/0002": "“蒂珐！究竟会发生什么！？”",
        }
        self.assertEqual(
            {entry_id: rows[entry_id] for entry_id in expected},
            expected,
        )

    def test_issue_043_thunder_break_uses_hong_tian_lei(self) -> None:
        rows = {row.entry_id: row.translation for row in self.rows}
        term = glossary_term("corpus/glossary/weapons-v1.json", "weapon/0021")
        self.assertEqual(term["translation"], "轰天雷")
        self.assertEqual(
            term["domains"],
            ["menu", "battle", "library"],
        )
        self.assertEqual(rows["battle:07278"], "“轰天雷！！”")
        self.assertEqual(rows["battle:20167"], "“轰天雷！！”")
        self.assertEqual(rows["battle:23254"], "“必杀力量！轰天雷！”")
        library = json.loads(
            (ROOT / "corpus/zh/library/v0.2-reviewed.json").read_text(
                encoding="utf-8"
            )
        )
        library_rows = {
            entry["id"]: entry["translation"] for entry in library["entries"]
        }
        self.assertIn("轰天雷", library_rows["library-text/0a97639e3ccccb09"])
        self.assertIn("轰天雷", library_rows["library-text/e57e516e2231e5e3"])

    def test_issue_044_story_wording_and_timp_address_stay_fixed(self) -> None:
        rows = {row.entry_id: row.translation for row in self.rows}
        expected = {
            "story/073/dialogue/02.01/0221": (
                "“也教教我吧！\n　我早就想试一次了！”"
            ),
            "story/073/dialogue/01.19/0007": (
                "“参谋长……你的表情放松下来了。”"
            ),
            "story/073/dialogue/02.02/0041": "“可恶的异星人！”",
            "story/073/dialogue/02.02/0103": "“……洛……卡洛……德……”",
        }
        self.assertEqual(
            {entry_id: rows[entry_id] for entry_id in expected},
            expected,
        )

        timp_to_jiron = (
            "story/040/dialogue/01.30/0004",
            "story/040/dialogue/01.30/0006",
            "story/040/dialogue/01.30/0011",
            "story/040/dialogue/01.53/0001",
            "story/040/dialogue/01.53/0004",
            "story/040/dialogue/01.53/0006",
            "story/043/dialogue/01.29/0002",
            "story/043/dialogue/01.30/0001",
            "story/043/dialogue/01.30/0002",
            "story/043/dialogue/01.31/0002",
            "story/043/dialogue/01.45/0001",
            "story/043/dialogue/01.46/0001",
            "story/073/dialogue/02.02/0013",
            "story/073/dialogue/02.02/0015",
            "story/073/dialogue/02.02/0017",
            "story/073/dialogue/02.02/0018",
            "story/091/dialogue/01.31/0000",
            "story/092/dialogue/01.38/0000",
            "story/117/dialogue/01.30/0002",
            "story/117/dialogue/01.59/0002",
            "story/117/dialogue/01.86/0002",
            "story/130/dialogue/01.35/0002",
            "story/130/dialogue/01.46/0002",
            "story/130/dialogue/01.70/0002",
        )
        self.assertEqual(len(timp_to_jiron), 24)
        for entry_id in timp_to_jiron:
            with self.subTest(entry_id=entry_id):
                self.assertIn("小哥", rows[entry_id])
                self.assertNotIn("大哥", rows[entry_id])
                self.assertNotIn("老兄", rows[entry_id])

    def test_common_machine_translation_scaffolding_stays_removed(self) -> None:
        for row in self.rows:
            with self.subTest(entry_id=row.entry_id):
                self.assertNotIn("这样下去的话", row.translation)
                self.assertNotRegex(row.translation, r"让我来让|让我们来让")
                self.assertNotRegex(
                    row.translation,
                    (
                        r"周边会受害|防止.{0,8}受害|这不任性|任性的舰长|"
                        r"自己的方便|凭自己的方便|按照自己的方便|对男人来说方便|"
                        r"卷进我的事情|事情的情报来源|保持这个调子"
                    ),
                )

        rows = {row.entry_id: row.translation for row in self.rows}
        self.assertEqual(
            rows["battle:09109"],
            "“抱歉…我这舰长太任性了…”",
        )
        self.assertEqual(
            rows["battle:00297"],
            "“你们本身就是纷争的种子…\\n　对我倒正合适”",
        )
        self.assertEqual(
            rows["battle:17431"],
            "“好节奏！\\n　下一发也照这个节奏来！”",
        )

    def test_attacking_and_falling_ochiru_lines_stay_distinguished(self) -> None:
        rows = {row.entry_id: row.translation for row in self.rows}
        attack_ids = {
            "battle:00895",
            "battle:04560",
            "battle:06493",
            "battle:06632",
            "battle:06677",
            "battle:06869",
            "battle:08159",
            "battle:11410",
            "battle:12402",
            "battle:13764",
            "battle:14191",
            "battle:14997",
            "battle:15001",
            "battle:15002",
            "battle:15105",
            "battle:17152",
            "battle:18418",
            "battle:18536",
            "battle:18606",
            "battle:18613",
            "battle:19765",
        }
        for entry_id in attack_ids:
            with self.subTest(entry_id=entry_id):
                self.assertIn("击落", rows[entry_id])
                self.assertNotIn("掉下去", rows[entry_id])

        falling_ids = {
            "battle:02726",
            "battle:12319",
            "battle:12340",
            "battle:15946",
            "battle:19846",
            "battle:23957",
        }
        for entry_id in falling_ids:
            with self.subTest(entry_id=entry_id):
                self.assertIn("掉下去", rows[entry_id])

    def test_reported_exodus_taunt_is_a_rhetorical_refusal(self) -> None:
        rows = {row.entry_id: row.translation for row in self.rows}
        self.assertEqual(
            rows["battle:08463"],
            "“怎么可能让你们大逃亡！”",
        )

    def test_katte_is_not_flattened_to_suibian(self) -> None:
        rows = {row.entry_id: row.translation for row in self.rows}
        expected = {
            "story/042/dialogue/02.01/0115":
                "“你这家伙！趁我不在就擅自聊起往事！”",
            "story/118/dialogue/02.01/0178":
                "“可不能让他们就这么发展下去。”",
            "story/137/dialogue/01.15/0001":
                "“哈哈哈哈！\n　自作主张创造世界，我可不答应！”",
            "battle:03442": "“哼！\\n　一个个都自说自话！”",
        }
        for entry_id, translation in expected.items():
            with self.subTest(entry_id=entry_id):
                self.assertEqual(rows[entry_id], translation)

    def test_iikagen_is_not_misread_as_appropriate(self) -> None:
        rows = {row.entry_id: row.translation for row in self.rows}
        self.assertEqual(
            rows["story/019/dialogue/02.03/0051"],
            "“差不多也该习惯我们了吧，\n　蒂珐·阿迪尔。”",
        )
        self.assertEqual(
            rows["story/122/dialogue/01.21/0006"],
            "“$n说得对。别什么事都自己扛，\n　也该适可而止了，不然会累垮的。”",
        )

    def test_amuro_newtype_value_exchange_is_natural_chinese(self) -> None:
        rows = {row.entry_id: row.translation for row in self.rows}
        expected = {
            "story/127/dialogue/02.02/0083":
                "“新人类也好，普通人也好……\n　这种区别没有任何意义。”",
            "story/127/dialogue/02.02/0084":
                "“至少，那种力量绝不该成为\n　衡量人类价值的标准。”",
            "story/127/dialogue/02.02/0087":
                "“人类另有力量能跨越这一切。”",
        }
        for entry_id, translation in expected.items():
            with self.subTest(entry_id=entry_id):
                self.assertEqual(rows[entry_id], translation)

    def test_musume_and_madowaseru_are_not_flattened_to_hanzi(self) -> None:
        rows = {row.entry_id: row.translation for row in self.rows}
        expected = {
            "story/089/dialogue/01.03/0005":
                "“闭嘴，突击丫头！\n　连那个带毛的都没拦住，我没空理你！”",
            "story/094/dialogue/01.03/0005":
                "“闭嘴，突击丫头！\n　连那个带毛的都没拦住，我没空理你！”",
            "battle:00589": "“别得意忘形，突击丫头——！！”",
            "story/052/dialogue/02.01/0148":
                "“你不也穿女装骗过我们吗！\n　还是说，那是你的兴趣！？”",
            "story/104/dialogue/01.45/0003":
                "“别说些让斗牙动摇的话！”",
        }
        for entry_id, translation in expected.items():
            with self.subTest(entry_id=entry_id):
                self.assertEqual(rows[entry_id], translation)

    def test_aisuru_is_not_rendered_as_spouse_or_compound_lover_heart(self) -> None:
        rows = {row.entry_id: row.translation for row in self.rows}
        self.assertEqual(
            rows["story/132/dialogue/02.02/0028"],
            "“你说得对……\n　我憎恨夺走深爱的迪拉尔生命的地球，\n　自愿接受了夺取三位一体能量的任务。”",
        )
        self.assertEqual(
            rows["story/132/dialogue/02.02/0034"],
            "“加根！你不会明白的！\n　爱一个人的心……正是祈愿和平的心！”",
        )

    def test_reported_amuro_and_apollo_battle_particles_stay_fixed(self) -> None:
        rows = {row.entry_id: row.translation for row in self.rows}
        self.assertEqual(rows["battle:01984"], "“躲开了吗！”")
        self.assertEqual(rows["battle:01730"], "“该死！窜来窜去的！”")

    def test_polished_battle_lines_fit_their_source_records(self) -> None:
        rows = {row.entry_id: row.translation for row in self.rows}
        self.assertEqual(rows["battle:03892"], "“不可能，威力这么强…！？”")
        self.assertEqual(rows["battle:07291"], "“铁也先生，交给我吧！”")
        self.assertEqual(rows["battle:09109"], "“抱歉…我这舰长太任性了…”")

    def test_reported_stage_22_to_24_wording_stays_fixed(self) -> None:
        rows = {row.entry_id: row.translation for row in self.rows}
        expected = {
            "story/043/dialogue/01.04/0000":
                "“那是什么？无脸怪吗！？”",
            "story/045/dialogue/01.09/0006":
                "“这是……伟大意志……？”",
            "story/047/dialogue/02.04/0025":
                "“不过，百鬼一族手段之高明，\n　着实令人惊叹。”",
            "story/048/dialogue/02.02/0079":
                "“请放心。我曾在其他地区成功平息混乱、\n　恢复秩序，对此很有信心。”",
        }
        for entry_id, translation in expected.items():
            with self.subTest(entry_id=entry_id):
                self.assertEqual(rows[entry_id], translation)

    def test_tetsuya_san_uses_the_existing_relationship_title(self) -> None:
        rows = [row for row in self.rows if "鉄也さん" in row.source_text]
        self.assertGreater(len(rows), 0)
        for row in rows:
            with self.subTest(entry_id=row.entry_id):
                self.assertIn("铁也先生", row.translation)
                self.assertNotIn("铁也哥", row.translation)

    def test_reported_stage_23_lines_stay_fixed(self) -> None:
        rows = {row.entry_id: row.translation for row in self.rows}
        expected = {
            "story/044/dialogue/02.01/0004":
                "“……嘿，原来KING他们也\n　经历过大逃亡啊。”",
            "story/044/dialogue/02.01/0015":
                "“啊哈哈，KING。祝你一路平安。”",
            "story/045/dialogue/02.01/0030":
                "“几乎就在你们与贝加大王决战、\n　被卷入时空转移的同时……”",
            "story/045/dialogue/01.06/0008":
                "“别说了，阿波罗……！”",
            "battle:24613": "“不、不、不可能！！”",
            "battle:24526": "“上吧！隼人、弁庆！”",
            "story/045/dialogue/01.20/0000":
                "“波士机器人！驾驶员是波士吗！？”",
            "story/045/dialogue/02.03/0020":
                "“正如罗杰君所说，百鬼帝国的侵略\n　手段既大胆，又缜密而狡猾。”",
            "story/045/dialogue/02.03/0044":
                "“既然政府和军方的人并非全是鬼，\n　轻举妄动可能招来杀身之祸。”",
        }
        for entry_id, translation in expected.items():
            with self.subTest(entry_id=entry_id):
                self.assertEqual(rows[entry_id], translation)

    def test_issue_023_identified_lines_stay_fixed(self) -> None:
        rows = {row.entry_id: row.translation for row in self.rows}
        expected = {
            "story/034/dialogue/02.03/0007":
                "“斯雷，给这位戴眼镜的小哥\n　挑些女孩子会喜欢的东西。”",
            "story/034/dialogue/02.03/0009":
                "“因为这位小哥好像也和你一样，\n　有想讨好的对象。”",
            "story/034/dialogue/02.03/0011":
                "“好好加油吧。\n　戴眼镜的小哥也是，斯雷也是。”",
            "story/034/dialogue/02.03/0016":
                "“盖纳……抱歉，给莎拉的礼物你自己找吧。”",
            "story/035/dialogue/01.05/0002":
                "“盖纳！该隐！我们都平安无事——！”",
            "story/036/dialogue/01.15/0000":
                "“那个黑色的大块头！是罗杰老兄吗！？”",
            "story/024/dialogue/01.42/0000":
                "“追寻真相的人啊！失去记忆、\n　死在这座城市，对你来说才是幸福！”",
            "story/024/dialogue/01.42/0002":
                "“如果你执意追寻真相，前方只有痛苦！\n　即便如此，你也要继续前进吗！”",
            "story/024/dialogue/01.43/0000":
                "“来吧，木乃伊混蛋！我要扯住你的绷带，\n　给你来个雅邦传统的扯带转圈！”",
            "story/024/dialogue/01.43/0002":
                "“亏你以前还是记者，\n　怎么连这个都不知道！”",
            "story/024/dialogue/01.43/0003":
                "“没错。我一无所知……不，曾经一无所知。\n　所以，我才想知道一切！”",
            "story/024/dialogue/01.43/0004":
                "“真相终将昭告天下！到那时，\n　这座城市存在的意义也会真相大白！”",
            "story/024/dialogue/01.43/0005":
                "“本想说随你便……可你既然对我出手了，\n　就得给我一个交代！”",
            "story/024/dialogue/01.43/0006":
                "“今天不搞大解体，改来一场绷带大切断！！”",
            "story/024/dialogue/02.02/0206": "“快逃！”",
            "story/024/dialogue/02.02/0424": "“快逃！”",
            "story/025/dialogue/02.04/0007": "“果然如此……”",
            "story/027/dialogue/02.01/0206":
                "“没办法，我就是适合干这种活……”",
            "battle:00612": "“来了啊！你这拈花惹草的恶党！”",
            "battle:22592": "“那种东西可打不中\\n　我兜甲儿大爷！”",
        }
        for entry_id, translation in expected.items():
            with self.subTest(entry_id=entry_id):
                self.assertEqual(rows[entry_id], translation)

    def test_explicit_japanese_gender_pronouns_do_not_flip_in_chinese(self) -> None:
        female_to_male = [
            row.entry_id
            for row in self.rows
            if "彼女" in row.source_text
            and "他" in row.translation
            and "她" not in row.translation
        ]
        male_to_female = [
            row.entry_id
            for row in self.rows
            if re.search(r"彼(?!女)", row.source_text)
            and "她" in row.translation
            and "他" not in row.translation
        ]
        self.assertEqual(female_to_male, [])
        self.assertEqual(male_to_female, [])

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

    def test_eureka_seven_terms_match_japanese_source_context(self) -> None:
        by_id = {
            term["id"]: term
            for term in load_global_glossary(ROOT / "corpus/glossary")
        }
        expected_occurrences = {
            "location/zonda-epta": 17,
            "unit/spearhead": 4,
            "organization/izumo-unit": 4,
            "unit/izumo-ship": 1,
            "people/lifter": 3,
            "item/lifting-board": 4,
            "item/reflection-film": 8,
            "unit/gekkostate-ship": 241,
            "organization/gekkostate": 223,
            "species/scub-coral": 122,
            "event/summer-of-love": 10,
            "concept/compac-drive": 14,
            "concept/amita-drive": 14,
            "concept/trapar-zone": 2,
            "organization/voderac": 79,
            "unit/nirvash-type-zero": 24,
            "unit/nirvash-the-end": 36,
            "species/coralian": 361,
            "people/ray": 306,
            "weapon/ray-pistol": 1,
        }
        report = audit_source_terms(
            self.rows,
            [by_id[term_id] for term_id in expected_occurrences],
        )
        self.assertEqual(report["source_occurrences"], expected_occurrences)
        self.assertEqual(report["mismatches"], [])

    def test_eureka_seven_adroc_motto_is_consistent(self) -> None:
        expected_fragments = {
            "ねだるな": ("不要哀求", 11),
            "勝ち取れ": ("学会争取", 10),
            "さすれば与えられん": ("若是如此，终有所获", 10),
        }
        for source_fragment, (translation_fragment, expected_count) in (
            expected_fragments.items()
        ):
            with self.subTest(source_fragment=source_fragment):
                rows = [
                    row for row in self.rows
                    if source_fragment in row.source_text
                ]
                self.assertEqual(len(rows), expected_count)
                self.assertTrue(
                    all(
                        translation_fragment
                        in row.translation.replace("\n", "").replace("　", "")
                        for row in rows
                    )
                )

    def test_getter_robo_g_terms_match_japanese_source_context(self) -> None:
        by_id = {
            term["id"]: term
            for term in load_global_glossary(ROOT / "corpus/glossary")
        }
        expected_occurrences = {
            "technology/getter-rays": 28,
            "unit/getter-short": 74,
            "unit/getter-robo": 105,
            "organization/getter-team": 38,
            "maneuver/open-get": 3,
            "unit/get-machines": 0,
            "unit/command-machine": 2,
            "unit/getter-g-dragon-form": 9,
            "unit/getter-g-liger-form": 10,
            "unit/getter-g-poseidon-form": 7,
            "organization/dinosaur-empire": 9,
            "organization/hyakki": 287,
            "people/burai": 64,
            "people/speaker-13cee73c14bf": 31,
            "people/speaker-1fe104411f19": 13,
            "people/speaker-2b47ba5ead9a": 23,
            "people/speaker-3bf5cd30c935": 58,
            "people/speaker-4aff9c305da4": 20,
            "people/speaker-7fc6e83611c6": 102,
            "people/speaker-809be7eb3803": 65,
            "people/speaker-9f0da37da623": 154,
            "people/speaker-be29ed800edf": 19,
            "people/speaker-ce1e8aeca780": 67,
            "people/speaker-ce2a3c67ca70": 64,
            "people/speaker-d34010c02035": 72,
            "unit/hyakki-robot": 11,
            "unit/lady-command": 2,
            "unit/mecha-fortress-oni": 7,
            "unit/mecha-tekkoki": 14,
            "unit/science-fortress-island": 15,
        }
        report = audit_source_terms(
            self.rows,
            [by_id[term_id] for term_id in expected_occurrences],
        )
        self.assertEqual(report["source_occurrences"], expected_occurrences)
        self.assertEqual(report["mismatches"], [])

    def test_baldios_terms_match_japanese_source_context(self) -> None:
        by_id = {
            term["id"]: term
            for term in load_global_glossary(ROOT / "corpus/glossary")
        }
        expected_occurrences = {
            "people/gattler-supreme-leader": 20,
            "people/supreme-leader-gattler": 2,
            "unit/baldios": 112,
            "unit/pulsar-burn": 14,
            "unit/new-pulsar-burn": 5,
            "unit/mini-pulsar-burn": 0,
            "unit/spirit-gattler": 6,
            "organization/blue-fixer": 33,
            "faction/aldébaran": 142,
            "people/marin": 398,
        }
        report = audit_source_terms(
            self.rows,
            [by_id[term_id] for term_id in expected_occurrences],
        )
        self.assertEqual(report["source_occurrences"], expected_occurrences)
        self.assertEqual(report["mismatches"], [])

    def test_god_sigma_terms_match_japanese_source_context(self) -> None:
        by_id = {
            term["id"]: term
            for term in load_global_glossary(ROOT / "corpus/glossary")
        }
        expected_occurrences = {
            "faction/elder": 3,
            "faction/elder-short": 250,
            "organization/elder-army": 26,
            "unit/eldar-battleship": 0,
            "unit/god-sigma": 117,
            "system/trinity-energy": 132,
            "place/trinity-city": 159,
            "place/trinity-base": 17,
            "people/gagan": 94,
            "people/teral": 237,
            "people/toshiya": 221,
            "people/speaker-b7d1aa88bb0a": 94,
            "people/speaker-2883579e5ff1": 45,
            "people/speaker-674a17f322f9": 9,
            "people/speaker-499d5f2ed87e": 21,
            "weapon/sigma-breast": 4,
        }
        report = audit_source_terms(
            self.rows,
            [by_id[term_id] for term_id in expected_occurrences],
        )
        self.assertEqual(report["source_occurrences"], expected_occurrences)
        self.assertEqual(report["mismatches"], [])

    def test_god_sigma_known_contamination_stays_fixed(self) -> None:
        wind_rows = {
            "story/120/dialogue/02.04/0018",
            "story/131/dialogue/01.93/0003",
            "story/131/dialogue/01.95/0004",
            "story/131/dialogue/02.03/0018",
            "story/131/dialogue/02.03/0031",
        }
        translations: dict[str, str] = {}
        for stage_index in (120, 131):
            document = json.loads(
                (ROOT / f"corpus/zh/story-dialogue/stage-{stage_index:03d}.json")
                .read_text(encoding="utf-8")
            )
            translations.update(
                {
                    row["id"]: row["translation"]
                    for row in document["entries"]
                    if row["id"] in wind_rows
                }
            )
        self.assertEqual(set(translations), wind_rows)
        self.assertTrue(
            all(
                all(word not in text for word in ("本王", "本大爷", "朕", "老子"))
                for text in translations.values()
            )
        )

        battle = (
            ROOT / "corpus/zh/battle/srvc-lines.json"
        ).read_text(encoding="utf-8")
        library = (
            ROOT / "corpus/zh/library/v0.2-reviewed.json"
        ).read_text(encoding="utf-8")
        self.assertNotIn("神、巨神西格玛", battle)
        self.assertNotIn("巨神飞翼", battle)
        self.assertNotIn("巨神飞翼", library)
        self.assertNotIn("西格玛胸炮", library)
        self.assertNotIn("西格玛·胸炮", library)
        self.assertNotIn("指尖针", library)

    def test_zambot_three_terms_match_japanese_source_context(self) -> None:
        by_id = {
            term["id"]: term
            for term in load_global_glossary(ROOT / "corpus/glossary")
        }
        expected_occurrences = {
            "concept/human-bomb": 58,
            "group/busu-pair": 6,
            "phrase/chiyonishiki-bark": 26,
            "unit/king-bial": 156,
            "unit/bial-short": 49,
            "location/bial-star": 20,
            "phrase/zambot-boost-short": 1,
            "weapon/0133": 2,
            "weapon/0142": 1,
            "weapon/0143": 1,
            "weapon/0137": 6,
            "weapon/zambot-grap": 1,
            "weapon/zambot-cutter": 1,
            "weapon/zambot-cross-slash": 2,
        }
        report = audit_source_terms(
            self.rows,
            [by_id[term_id] for term_id in expected_occurrences],
        )
        self.assertEqual(report["source_occurrences"], expected_occurrences)
        self.assertEqual(report["mismatches"], [])

    def test_zambot_three_known_contamination_stays_fixed(self) -> None:
        surfaces = "\n".join(
            (
                ROOT / relative_path
            ).read_text(encoding="utf-8")
            for relative_path in (
                "corpus/zh/battle/srvc-lines.json",
                "corpus/zh/library/v0.2-reviewed.json",
                "corpus/zh/menu/stage-overviews.json",
                "corpus/zh/story-dialogue/stage-009.json",
                "corpus/zh/story-dialogue/stage-026.json",
            )
        )
        for deprecated in (
            "人肉炸弹",
            "人间炸弹",
            "破坏者导弹",
            "震颤号角",
            "比亚尔王",
            "桑、赞波特",
        ):
            with self.subTest(deprecated=deprecated):
                self.assertNotIn(deprecated, surfaces)

    def test_daitarn_three_terms_match_japanese_source_context(self) -> None:
        by_id = {
            term["id"]: term
            for term in load_global_glossary(ROOT / "corpus/glossary")
        }
        expected_occurrences = {
            "unit/daitarn-three": 17,
            "unit/daitarn-short": 13,
            "people/banjo-haran-full": 34,
            "people/beautiful-tachibana-full": 1,
            "people/reika-sanjo-full": 2,
            "phrase/sun-is-with-me": 3,
            "weapon/0159": 1,
            "weapon/0160": 1,
            "weapon/0161": 1,
            "weapon/0162": 2,
            "weapon/0163": 2,
            "weapon/0164": 1,
            "weapon/daitarn-zanber": 2,
            "weapon/daitarn-fan": 1,
            "weapon/daitarn-leg-cannon": 1,
            "weapon/sun-laser-daitarn": 1,
        }
        report = audit_source_terms(
            self.rows,
            [by_id[term_id] for term_id in expected_occurrences],
        )
        self.assertEqual(report["source_occurrences"], expected_occurrences)
        self.assertEqual(report["mismatches"], [])

    def test_daitarn_three_known_contamination_stays_fixed(self) -> None:
        surfaces = "\n".join(
            (
                ROOT / relative_path
            ).read_text(encoding="utf-8")
            for relative_path in (
                "corpus/zh/battle/srvc-lines.json",
                "corpus/zh/library/v0.2-reviewed.json",
                "corpus/zh/story-dialogue/stage-098.json",
                "corpus/zh/story-dialogue/stage-107.json",
                "corpus/zh/story-dialogue/stage-119.json",
                "corpus/zh/story-dialogue/stage-139.json",
                "corpus/zh/story-dialogue/stage-143.json",
                "corpus/zh/story-dialogue/stage-148.json",
            )
        )
        for deprecated in (
            "戴坦",
            "梅加诺德",
            "梅加诺伊德",
            "机械诺伊德",
            "美丽橘",
            "泰坦斩刀",
            "泰坦斩刃",
            "日轮在我手中",
            "太阳攻击乱射",
        ):
            with self.subTest(deprecated=deprecated):
                self.assertNotIn(deprecated, surfaces)

    def test_orguss_terms_match_japanese_source_context(self) -> None:
        by_id = {
            term["id"]: term
            for term in load_global_glossary(ROOT / "corpus/glossary")
        }
        expected_occurrences = {
            "technology/great-singularity": 97,
            "technology/singularity": 261,
            "transform/gerwalk": 3,
            "transform/orguroid": 0,
            "organization/bronco-team": 2,
            "organization/black-men": 9,
            "title/black-man": 6,
            "civilization/mu": 59,
            "resource/blue-stone": 12,
            "name/nebulaad": 1,
            "unit/orguss": 18,
            "unit/orguss-ii": 0,
            "unit/bronco-ii": 3,
            "unit/moraver": 7,
            "unit/drifand": 4,
            "people/olson-d-verne-full": 15,
            "place/orguss-atlanta": 0,
        }
        report = audit_source_terms(
            self.rows,
            [by_id[term_id] for term_id in expected_occurrences],
        )
        self.assertEqual(report["source_occurrences"], expected_occurrences)
        self.assertEqual(report["mismatches"], [])

    def test_orguss_known_contamination_stays_fixed(self) -> None:
        surfaces = "\n".join(
            (
                ROOT / relative_path
            ).read_text(encoding="utf-8")
            for relative_path in (
                "corpus/zh/battle/srvc-lines.json",
                "corpus/zh/library/v0.2-reviewed.json",
                "corpus/zh/story-dialogue/stage-012.json",
                "corpus/zh/story-dialogue/stage-028.json",
                "corpus/zh/story-dialogue/stage-034.json",
                "corpus/zh/story-dialogue/stage-036.json",
                "corpus/zh/story-dialogue/stage-080.json",
                "corpus/zh/story-dialogue/stage-087.json",
                "corpus/zh/story-dialogue/stage-088.json",
                "corpus/zh/story-dialogue/stage-100.json",
                "corpus/zh/story-dialogue/stage-103.json",
                "corpus/zh/story-dialogue/stage-128.json",
                "corpus/zh/story-dialogue/stage-142.json",
                "corpus/zh/story-dialogue/stage-143.json",
                "corpus/zh/story-dialogue/stage-147.json",
                "corpus/zh/story-dialogue/stage-148.json",
            )
        )
        for deprecated in (
            "奥加斯",
            "姆乌",
            "布朗科队",
            "布隆科队",
            "黑男",
            "乘坐光粒子",
            "巨大奇点",
            "时空修正",
            "失去女性功能",
        ):
            with self.subTest(deprecated=deprecated):
                self.assertNotIn(deprecated, surfaces)

    def test_aquarion_terms_match_japanese_source_context(self) -> None:
        by_id = {
            term["id"]: term
            for term in load_global_glossary(ROOT / "corpus/glossary")
        }
        expected_occurrences = {
            "work/aquarion": 0,
            "organization/deava": 66,
            "place/deava-command-room": 3,
            "place/atlandia": 80,
            "species/mythic-beast": 8,
            "energy/prana": 4,
            "unit/cherubim-generic": 7,
            "people/speaker-94781288b465": 12,
            "unit/cherubim-mars": 8,
            "unit/cherubim-iscuron": 1,
            "unit/cherubim-shururukubera": 0,
            "unit/harvest-beast": 4,
            "unit/solar-aquarion": 0,
            "unit/aquarion-mars": 2,
            "unit/aquarion-luna": 2,
            "unit/aquarion-angel": 3,
            "unit/aquarion-alpha": 0,
            "unit/aquarion-omega": 0,
            "unit/aquarion-delta": 0,
            "unit/aquarion": 173,
            "unit/assault-aquarion": 7,
            "part/vector-machine": 1,
            "part/vector-sol": 6,
            "part/vector-mars": 3,
            "part/vector-luna": 1,
            "part/vector-delta": 0,
            "part/vector-alpha": 2,
            "part/vector-omega": 2,
            "people/speaker-66a2dbb4f5b6": 40,
            "people/sirius-de-alisia": 6,
            "people/silvia-de-alisia": 6,
            "concept/wings-of-sun": 116,
            "concept/tree-of-life": 67,
            "maneuver/genesis-union": 16,
            "item/book-of-genesis": 0,
            "energy/mythic-power": 8,
            "place/element-school": 33,
            "ability/element": 2,
            "place/alicia": 15,
        }
        report = audit_source_terms(
            self.rows,
            [by_id[term_id] for term_id in expected_occurrences],
        )
        self.assertEqual(report["source_occurrences"], expected_occurrences)
        self.assertEqual(report["source_occurrence_count"], 704)
        self.assertEqual(report["mismatches"], [])

    def test_aquarion_known_contamination_stays_fixed(self) -> None:
        paths = [
            ROOT / "corpus/zh/battle/srvc-lines.json",
            ROOT / "corpus/zh/library/v0.2-reviewed.json",
        ]
        paths.extend(sorted((ROOT / "corpus/zh/story-dialogue").glob("stage-*.json")))
        surfaces = "\n".join(path.read_text(encoding="utf-8") for path in paths)
        for deprecated in (
            "西里乌斯",
            "阿利西亚",
            "阿莉西娅",
            "多·阿莉西娅",
            "凯尔比姆",
            "凯鲁比姆",
            "凯鲁比姆",
            "亚库艾里翁 Mars",
            "亚库艾里翁，天使亚库艾里翁",
            "向量太阳",
            "维克托太阳",
            "神话之力",
            "收穫兽",
            "Plana",
            "普拉娜",
            "小都美",
            "都古美",
            "纯与都美",
            "鶫与皮耶尔",
            "同期进入元素学校的栞",
            "元素学院",
            "创圣3形态",
            "A—qua—ri—on",
        ):
            with self.subTest(deprecated=deprecated):
                self.assertNotIn(deprecated, surfaces)

    def test_seven_work_secondary_surfaces_use_reviewed_terms(self) -> None:
        formations = json.loads(
            (ROOT / "corpus/zh/menu/stage-default-formations.json").read_text(
                encoding="utf-8"
            )
        )["translations_by_source_text"]
        self.assertEqual(formations["ディーヴァ"], "DEAVA")
        self.assertEqual(formations["ザンボエース"], "赞波王牌")

        world_map = json.loads(
            (ROOT / "corpus/zh/ui-atlas/world-map-titles-v1.json").read_text(
                encoding="utf-8"
            )
        )["entries"]
        world_map_by_source = {entry["source"]: entry["translation"] for entry in world_map}
        self.assertEqual(world_map_by_source["アトランディア"], "亚特兰迪亚")
        self.assertEqual(
            world_map_by_source["ガリア大陸西部 ディーバ司令部"],
            "加利亚大陆西部 DEAVA司令部",
        )

        overview_entries = json.loads(
            (ROOT / "corpus/zh/menu/stage-overviews.json").read_text(
                encoding="utf-8"
            )
        )["entries"]
        overview = "".join(
            entry["translation"].replace("\n", "") for entry in overview_entries
        )
        for deprecated in ("Element们", "桑波Ace"):
            with self.subTest(deprecated=deprecated):
                self.assertNotIn(deprecated, overview)
        self.assertIn("元素能力者们", overview)
        self.assertIn("驾驶赞波王牌独自挑战异星人", overview)

        conditions = (
            ROOT / "corpus/zh/story-conditions.json"
        ).read_text(encoding="utf-8")
        self.assertNotIn("埃尔德战舰", conditions)

        menus = "\n".join(
            (ROOT / relative_path).read_text(encoding="utf-8")
            for relative_path in (
                "corpus/zh/menu/battle-lines.json",
                "corpus/zh/menu/system-ui-parts.json",
                "corpus/zh/menu/remaining-ui.json",
            )
        )
        self.assertIn("加根总司令", menus)
        self.assertNotIn("加冈总司令", menus)
        self.assertIn("矢量战机", menus)

    def test_supreme_leader_title_is_distinct_from_president(self) -> None:
        term = glossary_term(
            "corpus/glossary/global-variants-v1.json",
            "title/supreme-leader",
        )
        report = audit_source_terms(self.rows, [term])
        self.assertEqual(
            report["source_occurrences"],
            {"title/supreme-leader": 69},
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
        self.assertEqual(report["source_occurrences"], {term["id"]: 102})
        self.assertEqual(report["mismatches"], [])

        bound_rows = [
            row
            for row in self.rows
            if row.surface == "story" and "元気" in row.source_text
        ]
        self.assertEqual(len(bound_rows), 102)
        self.assertEqual(
            sum(term["id"] in row.glossary_exceptions for row in bound_rows),
            100,
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

    def test_issue_039_and_047_to_049_feedback_lines_stay_fixed(self) -> None:
        rows = {row.entry_id: row for row in self.rows}
        expected = {
            "battle:09461": "“你竟敢！”",
            "story/034/dialogue/02.03/0007": (
                "“斯雷，给这位戴眼镜的小哥\n　挑些女孩子会喜欢的东西。”"
            ),
            "story/034/dialogue/02.03/0009": (
                "“因为这位小哥好像也和你一样，\n　有想讨好的对象。”"
            ),
            "story/034/dialogue/02.03/0011": (
                "“好好加油吧。\n　戴眼镜的小哥也是，斯雷也是。”"
            ),
            "story/035/dialogue/01.05/0002": (
                "“盖纳！该隐！我们都平安无事——！”"
            ),
            "battle:00611": (
                "“拈花惹草的家伙，\\n　竟敢大摇大摆地现身——！！”"
            ),
            "battle:00612": "“来了啊！你这拈花惹草的恶党！”",
        }
        for entry_id, translation in expected.items():
            with self.subTest(entry_id=entry_id):
                self.assertEqual(rows[entry_id].translation, translation)

        self.assertIn("やったなぁっ", rows["battle:09461"].source_text)
        self.assertIn("私達は無事ですよーっ", rows["story/035/dialogue/01.05/0002"].source_text)
        self.assertIn("女ったらし", rows["battle:00611"].source_text)
        self.assertIn("女ったらし", rows["battle:00612"].source_text)

    def test_issue_051_and_052_battle_lines_stay_contextual(self) -> None:
        rows = {row.entry_id: row for row in self.rows}
        expected = {
            "battle:07804": ("シュート", "“发射！”"),
            "battle:23437": ("シュート", "“发射……！”"),
            "battle:14654": ("ファイヤーゴール", "“灼热的！火焰射门！！”"),
            "battle:06169": ("真っ向唐竹割り", "“迎头直劈！”"),
            "battle:24266": ("唐竹割り", "“唐竹斩！”"),
            "battle:24271": ("唐竹割り", "“唐竹斩！！”"),
        }
        for entry_id, (source_fragment, translation) in expected.items():
            with self.subTest(entry_id=entry_id):
                self.assertIn(source_fragment, rows[entry_id].source_text)
                self.assertEqual(rows[entry_id].translation, translation)

    def test_issue_058_setsuko_glory_star_cry_is_translated_by_meaning(self) -> None:
        rows = {row.entry_id: row for row in self.rows}
        expected = {
            "battle:11418": ("ハブ・ア・ゴー", "“放手一搏！！”"),
            "battle:11465": (
                "ハブ・ア・ゴー",
                "“连续射击…\\n　放手一搏…！”",
            ),
        }
        for entry_id, (source_fragment, translation) in expected.items():
            with self.subTest(entry_id=entry_id):
                self.assertIn(source_fragment, rows[entry_id].source_text)
                self.assertEqual(rows[entry_id].translation, translation)


if __name__ == "__main__":
    unittest.main()
