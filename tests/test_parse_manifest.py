import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = PROJECT_ROOT / "manifests" / "iso-data-parse.json"


class IsoDataParseManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_stable_id_total_matches_all_text_domains(self):
        parsed = self.manifest["parsed"]
        expected = sum(
            parsed[domain]["entry_count"]
            for domain in ("menu", "story", "summary")
        )
        self.assertEqual(parsed["stable_id_count"], expected)

    def test_story_entry_breakdown_is_complete(self):
        story = self.manifest["parsed"]["story"]
        self.assertEqual(
            story["entry_count"],
            story["speaker_count"]
            + story["condition_count"]
            + story["dialogue_count"],
        )

    def test_upstream_comparison_is_exact(self):
        comparison = self.manifest["upstream_xml_comparison"]
        self.assertTrue(comparison["exact"])
        self.assertEqual(comparison["differing_entry_count"], 0)
        for domain in ("menu", "story", "summary"):
            self.assertEqual(
                comparison[domain]["file_count"],
                comparison[domain]["exact_file_count"],
            )


if __name__ == "__main__":
    unittest.main()
