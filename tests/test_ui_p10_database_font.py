import json
import unittest
from collections import Counter
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = (
    PROJECT_ROOT
    / "config/encoding/ui-p10-database-font-allocations.json"
)
BASE_PROPOSAL_PATH = (
    PROJECT_ROOT / "work/writeback/ui-p7-embedded-codebook-proposal.json"
)
PROPOSAL_PATH = (
    PROJECT_ROOT / "work/writeback/ui-p10-database-codebook-proposal.json"
)
BUILD_REPORT_PATH = (
    PROJECT_ROOT
    / "work/build/ui-p10-database-font/components/font-validation.json"
)
MANIFEST_PATH = (
    PROJECT_ROOT / "manifests/ui-p10-database-font-validation.json"
)


class UiP10DatabaseFontTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = json.loads(
            REGISTRY_PATH.read_text(encoding="utf-8")
        )
        cls.base_proposal = json.loads(
            BASE_PROPOSAL_PATH.read_text(encoding="utf-8")
        )
        cls.proposal = json.loads(
            PROPOSAL_PATH.read_text(encoding="utf-8")
        )
        cls.build = json.loads(
            BUILD_REPORT_PATH.read_text(encoding="utf-8")
        )
        cls.manifest = json.loads(
            MANIFEST_PATH.read_text(encoding="utf-8")
        )

    def test_safe_gaps_then_source_glyph_reuse_are_bounded(self):
        self.assertEqual(
            self.registry["base_registry"]["registered_character_count"],
            724,
        )
        self.assertEqual(
            self.registry["appended_characters"],
            "+/乔佩俯农冻凉华吨呐咫喊喙喷圣垫妒嫣宾岑廖弯扩扳拂挡掷撕擒斩晓杆框桨桩歼涡漩灵烧猎疯绞绯绷缺肚脐臂芬荚药蛛蜃蜥蝰蟒贡赋赖踢轨辉辐邀钉钳钻铆铬链锤镜闪霆霰颤飓骑魇鹉鹦鹫鹰齿－",
        )
        capacity = self.manifest["capacity"]
        self.assertEqual(capacity["combined_registered_character_count"], 811)
        self.assertEqual(capacity["remaining_candidate_slot_count"], 2105)
        self.assertEqual(
            self.manifest["additional_allocations"]["source_glyph_reuse_count"],
            75,
        )

    def test_increment_reuses_four_codes_after_allocations_and_rerasters(self):
        added = [
            assignment
            for assignment in self.proposal["assignments"]
            if assignment["id"].startswith("ui-p10-database-")
        ]
        self.assertEqual(
            Counter(assignment["status"] for assignment in added),
            Counter(
                {
                    "proposed_allocation": 87,
                    "proposed_reraster": 99,
                    "proposed_semantic_reraster": 4,
                }
            ),
        )
        semantic = {
            assignment["character"]: {
                "code": assignment["code"],
                "glyph_index": assignment["glyph_index"],
                "mapping": assignment["mapping"],
                "status": assignment["status"],
                "source_character": assignment["source_character"],
            }
            for assignment in added
            if assignment["status"] == "proposed_semantic_reraster"
        }
        self.assertEqual(
            semantic,
            {
                "绊": {
                    "code": "E34A",
                    "glyph_index": 910,
                    "mapping": "pinned_text_table_semantic_replacement",
                    "status": "proposed_semantic_reraster",
                    "source_character": "絆",
                },
                "愤": {
                    "code": "95AE",
                    "glyph_index": 3950,
                    "mapping": "pinned_text_table_semantic_replacement",
                    "status": "proposed_semantic_reraster",
                    "source_character": "憤",
                },
                "眸": {
                    "code": "E1D2",
                    "glyph_index": 1026,
                    "mapping": "pinned_text_table_semantic_replacement",
                    "status": "proposed_semantic_reraster",
                    "source_character": "瞑",
                },
                "镰": {
                    "code": "88A0",
                    "glyph_index": 1440,
                    "mapping": "pinned_text_table_semantic_replacement",
                    "status": "proposed_semantic_reraster",
                    "source_character": "唖",
                },
            },
        )
        inherited = [
            assignment
            for assignment in self.proposal["assignments"]
            if not assignment["id"].startswith("ui-p10-database-")
        ]
        inherited_by_character = {
            assignment["character"]: assignment
            for assignment in inherited
        }
        base_by_character = {
            assignment["character"]: assignment
            for assignment in self.base_proposal["assignments"]
        }
        self.assertEqual(
            {
                character: assignment
                for character, assignment in inherited_by_character.items()
                if "optical_policy_tier" not in assignment
            },
            {
                character: assignment
                for character, assignment in base_by_character.items()
                if character not in inherited_by_character
                or "optical_policy_tier"
                not in inherited_by_character[character]
            },
        )
        optical = inherited_by_character["坠"]
        self.assertEqual(optical["code"], "83F6")
        self.assertEqual(optical["glyph_index"], 566)
        self.assertEqual(
            optical["status"],
            "proposed_inherited_optical_reraster",
        )
        self.assertEqual(optical["raster"]["point_size"], 23.5)
        self.assertEqual(
            optical["optical_override"]["point_size"],
            23.5,
        )
        cjk_assignments = [
            assignment
            for assignment in self.proposal["assignments"]
            if "optical_policy_tier" in assignment
        ]
        self.assertEqual(len(cjk_assignments), 1754)
        self.assertEqual(
            Counter(
                assignment["raster"]["point_size"]
                for assignment in cjk_assignments
            ),
            Counter({23: 700, 22.5: 445, 22: 388, 23.5: 220, 25: 1}),
        )
        self.assertEqual(
            {
                assignment["character"]
                for assignment in cjk_assignments
                if assignment["optical_policy_tier"]
                == "reviewed_exception"
            },
            {"班", "任", "坠", "尔"},
        )
        by_character = {
            assignment["character"]: assignment
            for assignment in cjk_assignments
        }
        self.assertEqual(by_character["您"]["raster"]["point_size"], 22)
        self.assertEqual(by_character["尔"]["raster"]["point_size"], 25)
        self.assertEqual(
            by_character["尔"]["raster"]["metrics"]["bbox_width"],
            22,
        )
        self.assertEqual(
            by_character["尔"]["raster"]["metrics"]["bbox_height"],
            22,
        )
        self.assertEqual(
            {by_character[character]["status"] for character in "凉缺"},
            {"proposed_allocation"},
        )

    def test_direct_opening_profile_is_a_locked_font_input(self):
        selection = self.manifest["inputs"]["database_selection"]
        self.assertEqual(
            selection["additional_translation_selections"],
            [
                {
                    "selection_id": "opening-protagonist-profile",
                    "path": "corpus/zh/menu/opening-protagonist-profile.json",
                    "sha256": "054e14d4060896e8b4bd76e388f32a74556a261424a15d17704e51cd57fe3e44",
                    "scene_id": "opening/protagonist-selection",
                    "entry_count": 4,
                    "entry_ids_sha256": "d7603f3e5c5baf069626d794f66ae4703723b7068d965f94b2a6cecd227604c8",
                    "selection_sha256": "3eb98012f287d1c80742571737c15ccc6943389ea71f72e2d0b09e2119b21d92",
                }
            ],
        )

    def test_database_renderer_coverage_is_complete_runtime_pending(self):
        coverage = self.manifest[
            "database_fixed_core_renderer_coverage"
        ]
        self.assertEqual(coverage["unique_entry_count"], 1470)
        self.assertEqual(coverage["missing_renderer_character_count"], 0)
        self.assertEqual(coverage["original_font_han_count"], 0)
        self.assertEqual(
            self.build["status"],
            "offline_font_validated_runtime_not_tested",
        )
        self.assertTrue(self.build["font"]["codec_round_trip_exact"])
        self.assertTrue(self.build["archive"]["offset_reread_exact"])
        self.assertEqual(self.manifest["runtime"]["status"], "not_tested")
        self.assertEqual(
            self.manifest["semantic_code_replacements"]["count"],
            4,
        )
        self.assertEqual(
            self.manifest["inherited_optical_reraster_overrides"][
                "entries"
            ][0]["character"],
            "坠",
        )
        self.assertEqual(
            self.manifest["cjk_optical_policy"]["point_size_counts"],
            {"22": 388, "22.5": 445, "23": 700, "23.5": 220, "25": 1},
        )
        self.assertEqual(
            self.manifest["cjk_optical_policy"]["raster_metrics"],
            {
                "empty_glyph_count": 0,
                "outer_edge_touch_count": 729,
                "bbox_width_min": 16,
                "bbox_width_median": 21.0,
                "bbox_width_max": 22,
                "bbox_height_min": 3,
                "bbox_height_median": 21.0,
                "bbox_height_max": 23,
                "ink_pixel_count_min": 61,
                "ink_pixel_count_median": 254.0,
                "ink_pixel_count_max": 365,
            },
        )


if __name__ == "__main__":
    unittest.main()
