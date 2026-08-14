import json
import tempfile
import unittest
from pathlib import Path

from tools.srwz.display_names import (
    DisplayNameError,
    load_display_name_source,
    load_full_unit_name_corpus,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STRUCTURE_PATH = PROJECT_ROOT / "config/display-names/compdata.json"
CORPUS_PATH = PROJECT_ROOT / "corpus/zh/display-names/units-full.json"


class FullUnitNameCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _config, _decoded, parsed, _context = load_display_name_source(
            PROJECT_ROOT,
            STRUCTURE_PATH,
        )
        cls.source_entries = parsed.unit_entries
        cls.decisions, cls.report = load_full_unit_name_corpus(
            PROJECT_ROOT,
            CORPUS_PATH,
            cls.source_entries,
        )

    def test_all_348_pointer_backed_name_slots_are_bound_once(self):
        self.assertEqual(len(self.decisions), 348)
        self.assertEqual(self.report["entry_count"], 348)
        self.assertEqual(
            list(self.decisions),
            [f"display-name/unit/{index:04d}/name" for index in range(348)],
        )
        self.assertEqual(
            sum(self.report["editorial_status_counts"].values()),
            348,
        )
        for index, source in enumerate(self.source_entries):
            decision = self.decisions[f"display-name/unit/{index:04d}/name"]
            self.assertEqual(decision["record_index"], index)
            self.assertEqual(decision["target_offset"], source.target_offset)
            self.assertEqual(decision["capacity"], source.capacity)
            self.assertEqual(
                decision["pointer_offsets"],
                list(source.pointer_offsets),
            )
            self.assertEqual(
                decision["source_text_sha256"],
                source.source_text_sha256,
            )

    def test_every_segment_has_attributable_sources_and_no_kana(self):
        self.assertTrue(
            all(decision["source_refs"] for decision in self.decisions.values())
        )
        kana = set("あいうえおアイウエオ")
        self.assertFalse(
            kana & set("".join(
                decision["translation"] for decision in self.decisions.values()
            ))
        )

    def test_gap_or_range_drift_fails_closed(self):
        document = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
        document["segments"][1]["range"][0] += 1
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as directory:
            path = Path(directory) / "units.json"
            path.write_text(
                json.dumps(document, ensure_ascii=False),
                encoding="utf-8",
            )
            with self.assertRaises(DisplayNameError):
                load_full_unit_name_corpus(
                    PROJECT_ROOT,
                    path,
                    self.source_entries,
                )

    def test_king_gainer_and_gravion_names_follow_reviewed_families(self):
        expected = {
            226: "拉什罗德",
            249: "超重皇",
            250: "神机超重神",
            251: "太阳超重王",
            252: "超重神西格玛",
            253: "超重骑警",
            254: "泽拉拜亚士兵",
            265: "G钻机",
            266: "G战影",
            267: "Geo幻象",
            268: "Geo投枪",
            269: "Geo圣剑",
            270: "Geo刺针",
            271: "Gran Σ",
            272: "超重要塞",
        }
        self.assertEqual(
            {
                index: self.decisions[
                    f"display-name/unit/{index:04d}/name"
                ]["translation"]
                for index in expected
            },
            expected,
        )

    def test_xabungle_unit_family_uses_mainland_reviewed_names(self):
        expected = {
            87: "萨芬格尔",
            88: "沃卡加利亚",
            89: "钢铁齿轮（LS）",
            90: "钢铁齿轮（WM）",
            98: "布洛克利",
        }
        self.assertEqual(
            {
                index: self.decisions[
                    f"display-name/unit/{index:04d}/name"
                ]["translation"]
                for index in expected
            },
            expected,
        )

    def test_gundam_x_unit_family_uses_mainland_reviewed_names(self):
        expected = {
            156: "高达X",
            157: "高达X分裂者",
            158: "高达X分裂者",
            159: "空中霸王爆裂者高达",
            160: "斑豹毁灭者高达",
            161: "高达DX",
            162: "高达DX+G猎鹰",
            163: "G猎鹰",
            164: "和平号",
            165: "杰尼斯改·艾妮尔专用",
            166: "艾斯佩兰扎",
            167: "维萨戈高达·破坏者",
            168: "阿斯塔隆高达HC",
            169: "拉斯维特",
            170: "加迪尔",
            171: "新多托列斯",
            172: "克鲁达",
            173: "帕特利亚",
            174: "贝迪哥",
            175: "D.O.M.E.G比特",
        }
        self.assertEqual(
            {
                index: self.decisions[
                    f"display-name/unit/{index:04d}/name"
                ]["translation"]
                for index in expected
            },
            expected,
        )

    def test_seed_destiny_unit_family_uses_mainland_reviewed_names(self):
        expected = {
            176: "强攻型脉冲高达",
            177: "巨剑型脉冲高达",
            178: "轰击型脉冲高达",
            182: "老虎烈焰型",
            184: "高机动型基恩II",
            198: "强袭嫣红",
            200: "拂晓高达",
            206: "密涅瓦",
            207: "加迪·鲁",
            214: "核心飞梭",
            215: "胸部飞行器",
            216: "腿部飞行器",
            217: "巨剑魅影",
            218: "强攻魅影",
        }
        self.assertEqual(
            {
                index: self.decisions[
                    f"display-name/unit/{index:04d}/name"
                ]["translation"]
                for index in expected
            },
            expected,
        )

    def test_big_o_unit_family_uses_reviewed_names(self):
        expected = {
            239: "BIG-O",
            240: "木乃伊",
            241: "BIG-DUO",
            242: "BIG-DUO地狱",
            243: "BIG-FAU",
            244: "贝克·胜利·豪华型",
            245: "贝克·大帝RX3",
            246: "原型",
            247: "波拿巴",
            248: "草原犬鼠",
        }
        self.assertEqual(
            {
                index: self.decisions[
                    f"display-name/unit/{index:04d}/name"
                ]["translation"]
                for index in expected
            },
            expected,
        )

    def test_zeta_and_chars_counterattack_use_mainland_reviewed_names(self):
        expected = {
            111: "里克·迪亚斯",
            140: "灵·格斯",
            141: "ν高达",
        }
        self.assertEqual(
            {
                index: self.decisions[
                    f"display-name/unit/{index:04d}/name"
                ]["translation"]
                for index in expected
            },
            expected,
        )


if __name__ == "__main__":
    unittest.main()
