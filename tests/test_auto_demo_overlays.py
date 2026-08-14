import json
import unittest
from pathlib import Path

from tools import build_full_story_components
from tools.srwz.auto_demo import discover_auto_demo_name_slots


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class AutoDemoOverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(
            (PROJECT_ROOT / "config/full-story-components.json").read_text(
                encoding="utf-8"
            )
        )
        cls.auto_demo = cls.config["auto_demo_overlays"]

    def test_locked_archives_have_complete_name_inventory(self):
        counts = []
        sources = set()
        for archive in self.auto_demo["battle_archives"]:
            payload = (PROJECT_ROOT / archive["source"]["path"]).read_bytes()
            seg = (PROJECT_ROOT / archive["seg"]["path"]).read_bytes()
            slots = discover_auto_demo_name_slots(payload, seg)
            counts.append(len(slots))
            sources.update(slot.source_text for slot in slots)
        self.assertEqual(counts, [20, 19, 24])
        self.assertEqual(sum(counts), 63)
        self.assertEqual(len(sources), 59)
        self.assertIn("カミーユ", sources)
        self.assertIn("Ｔボーン", sources)
        self.assertIn("ダヴ", sources)

    def test_writeback_reuses_existing_titles_and_names(self):
        font_manifest = json.loads(
            (
                PROJECT_ROOT / "manifests/zh-release-font-validation.json"
            ).read_text(encoding="utf-8")
        )
        source_slps = (
            PROJECT_ROOT / self.auto_demo["original_slps"]["path"]
        ).read_bytes()
        output_slps, archives, report, _paths = (
            build_full_story_components._apply_auto_demo_overlays(
                source_slps,
                self.auto_demo,
                font_manifest,
            )
        )
        self.assertEqual(len(output_slps), len(source_slps))
        self.assertEqual(report["title_entry_count"], 22)
        self.assertEqual(report["name_slot_count"], 63)
        self.assertTrue(report["translated_reread_exact"])
        self.assertEqual(report["titles"][10]["source_text"], "機動戦士Ｚガンダム")
        self.assertEqual(report["titles"][10]["translation"], "机动战士Z高达")
        self.assertEqual(
            report["titles"][11]["translation"],
            "机动战士高达：逆袭的夏亚",
        )
        kamille = [
            name
            for archive in report["archives"]
            for name in archive["names"]
            if name["source_text"] == "カミーユ"
        ]
        self.assertEqual(len(kamille), 1)
        self.assertEqual(kamille[0]["offset"], 0x40B0C)
        self.assertEqual(kamille[0]["translation"], "卡缪")
        self.assertEqual(
            set(archives),
            {"BTL/OP0.BIN", "BTL/OP1.BIN", "BTL/OP2.BIN"},
        )


if __name__ == "__main__":
    unittest.main()
