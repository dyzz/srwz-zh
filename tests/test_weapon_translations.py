import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRANSLATIONS_PATH = (
    PROJECT_ROOT / "corpus" / "zh" / "menu" / "weapons.json"
)
GLOSSARY_PATH = (
    PROJECT_ROOT / "corpus" / "glossary" / "weapons-v1.json"
)
RELEASE_PATH = PROJECT_ROOT / "corpus" / "releases" / "v1.json"


class WeaponTranslationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.translations = json.loads(
            TRANSLATIONS_PATH.read_text(encoding="utf-8")
        )
        cls.glossary = json.loads(
            GLOSSARY_PATH.read_text(encoding="utf-8")
        )

    def test_all_weapon_records_have_one_matching_canonical_term(self):
        entries = self.translations["entries"]
        terms = self.glossary["terms"]

        self.assertEqual(self.translations["batch_id"], "v1-menu-weapons")
        self.assertEqual(self.translations["scope"]["entry_count"], 711)
        self.assertEqual(len(entries), 711)
        self.assertEqual(len(terms), 711)

        for ordinal, (entry, term) in enumerate(zip(entries, terms)):
            entry_id = f"menu/Compdata/02/{ordinal:04d}"
            term_id = f"weapon/{ordinal:04d}"
            self.assertEqual(entry["id"], entry_id)
            self.assertRegex(entry["source_text_sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(entry["editorial_status"], "draft")
            self.assertIn(term_id, entry["glossary_refs"])
            self.assertEqual(term["id"], term_id)
            self.assertEqual(term["translation"], entry["translation"])
            self.assertEqual(term["category"], "weapon")
            self.assertEqual(term["domains"], ["menu"])
            self.assertFalse(term["enforce"])

    def test_high_risk_weapon_decisions_remain_explicit(self):
        entries = {
            int(entry["id"].rsplit("/", 1)[1]): entry
            for entry in self.translations["entries"]
        }
        expected = {
            1: "硫酸飓风",
            64: "双战斧",
            270: "ν超级火箭筒",
            352: "MA-M941“金刚杵”光束军刀",
            372: "光束突击枪（连射）",
            448: "分离式统合控制高速机动兵装群网络系统（连射）",
            518: "光子垫",
            638: "第七波动",
            650: "队形·加贡多拉",
            709: "灵脉爆破",
        }
        self.assertEqual(
            {ordinal: entries[ordinal]["translation"] for ordinal in expected},
            expected,
        )
        self.assertIn("technology/photon-mat", entries[518]["glossary_refs"])
        self.assertIn("system/formation", entries[650]["glossary_refs"])

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
        self.assertEqual(batch["status"], "draft_complete")


if __name__ == "__main__":
    unittest.main()
