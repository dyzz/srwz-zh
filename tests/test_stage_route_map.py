import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STAGE_TRANSLATIONS = (
    PROJECT_ROOT / "corpus" / "zh" / "menu" / "stage-names.json"
)
ROUTE_MAP = PROJECT_ROOT / "docs" / "STAGE_ROUTE_MAP.md"


class StageRouteMapTests(unittest.TestCase):
    def test_opening_titles_are_finalized_without_glyph_compromise(self):
        document = json.loads(STAGE_TRANSLATIONS.read_text(encoding="utf-8"))
        entries = document["entries"][:5]
        self.assertEqual(
            [entry["translation"] for entry in entries],
            ["太空先锋", "愤怒的眼眸", "两个世界", "异星人来袭", "觉醒之日"],
        )
        self.assertTrue(
            all(entry["editorial_status"] == "final" for entry in entries)
        )

    def test_route_map_contains_every_playable_title_translation(self):
        document = json.loads(STAGE_TRANSLATIONS.read_text(encoding="utf-8"))
        translations = {
            int(entry["id"].rsplit("/", 1)[1]): entry["translation"]
            for entry in document["entries"]
        }
        route_map = ROUTE_MAP.read_text(encoding="utf-8")

        self.assertEqual(set(translations), set(range(122)))
        for ordinal in range(107):
            self.assertIn(
                f"`[{ordinal:03d}]` {translations[ordinal]}",
                route_map,
            )

    def test_route_map_keeps_nonchapter_records_separate(self):
        document = json.loads(STAGE_TRANSLATIONS.read_text(encoding="utf-8"))
        translations = {
            int(entry["id"].rsplit("/", 1)[1]): entry["translation"]
            for entry in document["entries"]
        }
        route_map = ROUTE_MAP.read_text(encoding="utf-8")

        for ordinal in range(107, 118):
            self.assertIn(
                f"| {ordinal} | {translations[ordinal]}",
                route_map,
            )
        self.assertIn("| 118 | 空字符串 | 空白占位 |", route_map)
        for ordinal in range(119, 122):
            self.assertIn(
                f"| {ordinal} | {translations[ordinal]}",
                route_map,
            )


if __name__ == "__main__":
    unittest.main()
