import json
import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRANSLATIONS_PATH = (
    PROJECT_ROOT / "corpus" / "zh" / "menu" / "weapons.json"
)
GLOSSARY_PATH = (
    PROJECT_ROOT / "corpus" / "glossary" / "weapons-v1.json"
)
BATTLE_TRANSLATIONS_PATH = (
    PROJECT_ROOT / "corpus" / "zh" / "battle" / "srvc-lines.json"
)
RELEASE_PATH = PROJECT_ROOT / "corpus" / "releases" / "v1.json"
COMPONENT_MANIFEST_PATH = (
    PROJECT_ROOT / "manifests" / "full-story-components-validation.json"
)


class WeaponTranslationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.translations = json.loads(
            TRANSLATIONS_PATH.read_text(encoding="utf-8")
        )
        cls.glossary = json.loads(
            GLOSSARY_PATH.read_text(encoding="utf-8")
        )
        cls.battle_translations = json.loads(
            BATTLE_TRANSLATIONS_PATH.read_text(encoding="utf-8")
        )

    def test_all_weapon_records_have_one_matching_canonical_term(self):
        entries = self.translations["entries"]
        terms = [
            term
            for term in self.glossary["terms"]
            if re.fullmatch(r"weapon/[0-9]{4}", term["id"])
        ]
        fixed_span_display_contractions = {
            167: "爆雷",
            345: "荷粒子炮",
            399: "低反动炮",
            400: "Mk39低反动炮",
            401: "低反动炮（连射）",
            402: "Mk39低反动炮（连射）",
            505: "XM47特里斯坦",
            519: "超限攻击",
            544: "超限连击",
            553: "Big O·最终舞台",
            565: "格兰骑士攻击",
            673: "HEAT CRUSHER",
        }

        self.assertEqual(self.translations["batch_id"], "v1-menu-weapons")
        self.assertEqual(self.translations["scope"]["entry_count"], 711)
        self.assertEqual(len(entries), 711)
        self.assertEqual(len(terms), 711)

        for ordinal, (entry, term) in enumerate(zip(entries, terms)):
            entry_id = f"menu/Compdata/02/{ordinal:04d}"
            term_id = f"weapon/{ordinal:04d}"
            self.assertEqual(entry["id"], entry_id)
            self.assertRegex(entry["source_text_sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(entry["editorial_status"], "reviewed")
            self.assertIn(term_id, entry["glossary_refs"])
            self.assertEqual(term["id"], term_id)
            if ordinal in fixed_span_display_contractions:
                self.assertEqual(
                    entry["translation"],
                    fixed_span_display_contractions[ordinal],
                )
                self.assertNotEqual(
                    term["translation"],
                    entry["translation"],
                )
                if ordinal == 673:
                    self.assertEqual(
                        entry["fixed_span_display_contraction"],
                        term["translation"],
                    )
            else:
                self.assertEqual(term["translation"], entry["translation"])
            self.assertIn(term["category"], {"weapon", "epithet"})
            if term["category"] == "epithet":
                self.assertEqual(term["id"], "weapon/0527")
            self.assertEqual(term["status"], "approved")
            self.assertIn("menu", term["domains"])
            self.assertLessEqual(
                set(term["domains"]),
                {"menu", "battle", "library", "story"},
            )
            self.assertEqual(term["enforce"], len(term["domains"]) > 1)

    def test_high_risk_weapon_decisions_remain_explicit(self):
        entries = {
            int(entry["id"].rsplit("/", 1)[1]): entry
            for entry in self.translations["entries"]
        }
        expected = {
            1: "腐蚀飓风",
            21: "轰天雷",
            64: "双战斧",
            97: "雷霆闪光",
            195: "沃卡加利亚全功率",
            217: "布洛克利全功率",
            270: "ν超级火箭筒",
            352: "MA-M941“金刚杵式”光束军刀",
            372: "光束突击枪（连射）",
            448: "分离式统合控制高速机动兵装群网络系统（连射）",
            518: "光子垫",
            550: "铁腕猛击",
            638: "七波",
            650: "队形·加贡多拉",
            709: "灵脉爆破",
        }
        self.assertEqual(
            {ordinal: entries[ordinal]["translation"] for ordinal in expected},
            expected,
        )
        self.assertIn("technology/photon-mat", entries[518]["glossary_refs"])
        self.assertIn("system/formation", entries[650]["glossary_refs"])

    def test_baldios_split_attack_calls_match_thunder_flash_name(self):
        by_id = {
            entry["id"]: entry["translation"]
            for entry in self.battle_translations["entries"]
        }
        self.assertEqual(by_id["battle:17870"], "“上了！雷——霆——！”")
        self.assertEqual(by_id["battle:17871"], "“闪——光！！”")
        self.assertEqual(by_id["battle:17874"], "“雷——霆——！”")

    def test_v1_release_registers_complete_weapon_batch(self):
        release = json.loads(RELEASE_PATH.read_text(encoding="utf-8"))
        self.assertIn(
            "corpus/zh/menu/weapons.json",
            release["translation_sources"],
        )
        self.assertIn(
            "corpus/glossary/weapons-v1.json",
            release["glossary_sources"],
        )
        batch = next(
            batch
            for batch in release["coverage_plan"]
            if batch["batch_id"] == "v1-menu-weapons"
        )
        self.assertEqual(batch["target_entry_count"], 711)
        self.assertEqual(batch["status"], "reviewed_complete")

    def test_king_gainer_and_gravion_subtitle_decisions_stay_aligned(self):
        entries = {
            int(entry["id"].rsplit("/", 1)[1]): entry["translation"]
            for entry in self.translations["entries"]
        }
        terms = {
            int(term["id"].rsplit("/", 1)[1]): term["translation"]
            for term in self.glossary["terms"]
            if re.fullmatch(r"weapon/[0-9]{4}", term["id"])
        }
        menu_expected = {
            516: "电锯枪（射击）",
            517: "电锯枪（斩击）",
            519: "超限攻击",
            527: "黑色南十字星",
            544: "超限连击",
            566: "超重压力拳",
            567: "超重飞弹",
            568: "超重来福枪",
            570: "超重龙卷拳",
            571: "超重弧光",
            572: "超重新月镖",
            574: "烈阳超重旋腕击",
            575: "烈阳超重翔腕碎",
            576: "烈阳超重飞弹",
            577: "烈阳超重加农",
            579: "烈阳超重翔灭钻炎爆",
            580: "烈阳超重翔灭钻炎爆",
            581: "烈阳超重爆炎霸",
            584: "超重骑枪",
            585: "重力放射镖",
        }
        self.assertEqual(
            {ordinal: entries[ordinal] for ordinal in menu_expected},
            menu_expected,
        )
        self.assertEqual(terms[519], "超限战术攻击")
        self.assertEqual(terms[544], "超限战术连击")

    def test_reviewed_weapon_batch_is_written_into_the_integrated_compdata(self):
        component = json.loads(
            COMPONENT_MANIFEST_PATH.read_text(encoding="utf-8")
        )
        report = component["reviewed_weapons"]
        self.assertEqual(report["corpus_entry_count"], 711)
        self.assertEqual(report["unique_target_count"], 711)
        self.assertEqual(report["shared_nonweapon_owner_count"], 1)
        self.assertEqual(
            report["shared_nonweapon_owner_ids"],
            ["menu/Compdata/04/0031"],
        )
        self.assertTrue(report["source_preimages_sha256_exact"])
        self.assertTrue(report["target_offset_reread_exact"])
        self.assertTrue(report["codec_round_trip_exact"])
        self.assertTrue(
            component["acceptance"]["reviewed_weapon_names_reread_exact"]
        )



if __name__ == "__main__":
    unittest.main()
