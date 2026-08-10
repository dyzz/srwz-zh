import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMPONENT_MANIFEST = (
    PROJECT_ROOT / "manifests/full-story-components-validation.json"
)


class CurrentResidualUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.component = json.loads(
            COMPONENT_MANIFEST.read_text(encoding="utf-8")
        )

    def test_fixed_slps_and_suspend_return_dialogue_are_locked(self):
        remaining = self.component["remaining_ui"]
        self.assertEqual(remaining["slps_context_ui"]["entry_count"], 407)
        self.assertEqual(remaining["slps"]["entry_count"], 172)

        formation = remaining["stage_default_formation"]
        self.assertEqual(formation["entry_count"], 17)
        self.assertEqual(formation["stage_indices"], [1, 203])
        self.assertEqual(
            formation["translations"],
            [
                {"source": "エゥーゴ", "translation": "奥古"},
                {
                    "source": "グローリー・スター１",
                    "translation": "荣耀之星1",
                },
                {
                    "source": "グローリー・スター２",
                    "translation": "荣耀之星2",
                },
                {
                    "source": "グローリー・スター３",
                    "translation": "荣耀之星3",
                },
            ],
        )
        self.assertTrue(formation["fixed_allocations_preserved"])
        self.assertTrue(formation["slot_padding_zero"])
        self.assertTrue(formation["reread_exact"])

        dialogue = remaining["stage_system_dialogue"]
        self.assertEqual(dialogue["selected_entry_count"], 379)
        self.assertEqual(dialogue["inventory_entry_count"], 379)
        self.assertEqual(
            dialogue["selected_pointer_offsets_sha256"],
            "296c64123f0587124a1583935d522f189ba0e9e992feb774ec3e4173b793a058",
        )
        self.assertTrue(dialogue["source_preimages_sha256_exact"])
        self.assertTrue(dialogue["pointer_bytes_unchanged"])
        self.assertTrue(dialogue["reread_exact"])
        self.assertTrue(dialogue["codec_round_trip_exact"])
        self.assertTrue(dialogue["archive_size_preserved"])
        self.assertTrue(dialogue["hb_offsets_preserved"])

    def test_all_discovered_terrain_names_are_reencoded(self):
        terrain = self.component["world_map_titles"]["terrain_names"]
        self.assertEqual(terrain["unique_source_count"], 15)
        self.assertEqual(terrain["occurrence_count"], 66)
        self.assertEqual(terrain["changed_member_count"], 10)
        self.assertTrue(terrain["fixed_decoded_spans_preserved"])
        self.assertTrue(terrain["archive_size_preserved"])
        self.assertTrue(terrain["offset_table_preserved"])
        self.assertTrue(terrain["codec_round_trip_exact"])
        self.assertTrue(terrain["reread_exact"])


if __name__ == "__main__":
    unittest.main()
