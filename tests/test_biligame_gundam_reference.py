import json
import unittest
from pathlib import Path

from tools.build_biligame_gundam_reference import (
    extract_detail_facts,
    extract_people_entries,
    extract_unit_entries,
    page_source_url,
    page_title,
    parse_wiki_links,
)


class BiligameGundamReferenceTests(unittest.TestCase):
    def test_committed_lock_keeps_review_only_boundary(self):
        root = Path(__file__).resolve().parents[1]
        lock = json.loads(
            (
                root
                / "corpus/reference/biligame-srwz-gundam.lock.json"
            ).read_text(encoding="utf-8")
        )
        self.assertFalse(lock["scope"]["authoritative_for_non_gundam"])
        self.assertFalse(lock["scope"]["auto_apply"])
        self.assertEqual(
            lock["derived_index"]["unique_person_count"],
            344,
        )
        self.assertEqual(
            lock["derived_index"]["live_unit_index_entry_count"],
            3023,
        )

    def test_first_five_selected_names_have_been_migrated(self):
        root = Path(__file__).resolve().parents[1]
        review = json.loads(
            (
                root
                / "corpus/review/first-five-gundam-roster-variants-v1.json"
            ).read_text(encoding="utf-8")
        )
        candidates = review["migration_candidates"]
        self.assertEqual(len(candidates), 12)
        self.assertTrue(
            all(
                candidate["decision_status"] == "adopted_in_corpus"
                for candidate in candidates
            )
        )
        self.assertEqual(
            {
                candidate["id"]: candidate["current_translation"]
                for candidate in candidates
            },
            {
                "alex-dino": "亚历士",
                "emma-sheen": "爱玛／爱玛·辛",
                "jerid-messa": "捷利特／捷利特·梅萨",
                "roberto": "罗伯托",
                "kacricon-cacooler": "卡克里孔／卡克里孔·卡库拉",
                "lunamaria-hawke": "露娜玛利亚／露娜",
                "talia-gladys": "塔丽亚／库拉迪斯舰长",
                "arthur-trine": "阿瑟／阿瑟·川恩",
                "neo-roanoke": "尼奥／尼奥·罗阿诺克",
                "exus": "埃格萨斯",
                "girty-lue": "加迪·鲁",
                "jamaican-daninghan": "牙买加",
            },
        )

    def test_first_five_text_contains_no_superseded_gundam_names(self):
        root = Path(__file__).resolve().parents[1]
        documents = [
            json.loads(
                (
                    root
                    / "corpus/zh/story-dialogue"
                    / f"stage-{stage:03d}.json"
                ).read_text(encoding="utf-8")
            )
            for stage in range(1, 6)
        ]
        for name in ("story-conditions", "story-speakers"):
            document = json.loads(
                (root / f"corpus/zh/{name}.json").read_text(
                    encoding="utf-8"
                )
            )
            documents.append(
                {
                    **document,
                    "entries": [
                        entry
                        for entry in document["entries"]
                        if int(entry["id"].split("/")[1]) <= 5
                    ],
                }
            )
        text = "\n".join(
            entry["translation"]
            for document in documents
            for entry in document["entries"]
        )
        for superseded in (
            "亚历克斯",
            "艾玛",
            "杰利特",
            "罗伯特",
            "卡克里孔·卡克拉",
            "露娜玛丽亚",
            "塔莉娅",
            "格拉迪斯舰长",
            "亚瑟",
            "亚瑟·托莱恩",
            "尼奥·罗安那克",
            "艾克萨斯",
            "葛蒂·露",
            "贾迈肯",
            "达宁冈",
        ):
            with self.subTest(superseded=superseded):
                self.assertNotIn(superseded, text)
        for selected in (
            "亚历士",
            "爱玛",
            "捷利特",
            "罗伯托",
            "卡克里孔·卡库拉",
            "露娜玛利亚",
            "塔丽亚",
            "库拉迪斯舰长",
            "阿瑟",
            "阿瑟·川恩",
            "尼奥·罗阿诺克",
            "埃格萨斯",
            "加迪·鲁",
            "牙买加·达宁汉",
        ):
            with self.subTest(selected=selected):
                self.assertIn(selected, text)

    def test_people_page_keeps_live_character_links_only(self):
        text = """Source URL: https://wiki.biligame.com/gundam/作品人物
# 作品人物
## 阵营
[角色甲](https://wiki.biligame.com/gundam/角色甲 "角色甲")
[角色甲](https://wiki.biligame.com/gundam/角色甲 "角色甲")
[不存在](https://wiki.biligame.com/gundam/index.php?title=不存在&action=edit&redlink=1 "不存在")
[分类](https://wiki.biligame.com/gundam/分类:人物 "分类:人物")
取自“source”
"""
        entries = extract_people_entries(
            "作品人物",
            "https://wiki.biligame.com/gundam/作品人物",
            text,
        )
        self.assertEqual(
            entries,
            (
                {
                    "category": "person",
                    "series": "作品",
                    "zh_title": "角色甲",
                    "url": "https://wiki.biligame.com/gundam/角色甲",
                },
            ),
        )

    def test_unit_index_skips_redlinks(self):
        text = """Source URL: https://wiki.biligame.com/gundam/全机体资料
# 全机体资料
## A-D开头型号
[机体甲](https://wiki.biligame.com/gundam/机体甲 "机体甲")
[红链](https://wiki.biligame.com/gundam/index.php?title=红链&action=edit&redlink=1 "红链")
取自“source”
"""
        self.assertEqual(
            extract_unit_entries(text),
            (
                {
                    "category": "unit",
                    "series": "",
                    "zh_title": "机体甲",
                    "url": "https://wiki.biligame.com/gundam/机体甲",
                },
            ),
        )

    def test_detail_fields_remain_separate(self):
        text = """Source URL: https://wiki.biligame.com/gundam/TS-MA4F埃格萨斯
# TS-MA4F埃格萨斯
| 机体型号 | TS-MA4F | 中文名称 | 埃格萨斯 |
| 日文名称 | エグザス | 英文名称 | Exus |
"""
        source_url = page_source_url(text)
        title = page_title(text, source_url)
        facts = extract_detail_facts(title, source_url, text)
        self.assertEqual(facts["zh_name"], "埃格萨斯")
        self.assertEqual(facts["jp_name"], "エグザス")
        self.assertEqual(facts["title"], "TS-MA4F埃格萨斯")

    def test_plain_and_titled_links_are_deduplicated(self):
        text = (
            '[甲](https://wiki.biligame.com/gundam/甲 "甲")'
            "[甲](https://wiki.biligame.com/gundam/甲)"
        )
        self.assertEqual(len(parse_wiki_links(text)), 1)


if __name__ == "__main__":
    unittest.main()
