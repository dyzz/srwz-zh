from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools.srwz.tim2_writeback import CANARY_HEIGHT, CANARY_WIDTH
from tools.srwz.ui_atlas_canary import AtlasMask
from tools.srwz.ui_atlas_localization import (
    UiAtlasLocalizationError,
    apply_indexed_text_layers,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class UiAtlasLocalizationTest(unittest.TestCase):
    def test_absolute_outline_coverage_keeps_low_fringe_pixels_dark(self) -> None:
        mask = AtlasMask.from_mapping(
            {
                "x": 0,
                "y": 0,
                "width": 3,
                "height": 1,
                "replacement_rgba": "00000000",
                "preserve_rgba": ["00000000"],
            }
        )
        erased = bytes(CANARY_WIDTH * CANARY_HEIGHT * 4)
        outline_mask = bytes((1, 12, 0))
        fill_mask = bytes((0, 0, 255))
        layers = {
            "outline": tuple(
                (bytes((level, level, level, 0xFF)), level)
                for level in range(1, 8)
            ),
            "fill": (
                (bytes((8, 8, 8, 0xFF)), 8),
                (bytes((15, 15, 15, 0xFF)), 15),
            ),
        }

        _default_rgba, default_audit, _default_indexes = (
            apply_indexed_text_layers(
                erased,
                outline_mask,
                fill_mask,
                mask,
                layers,
            )
        )
        _fixed_rgba, fixed_audit, fixed_indexes = apply_indexed_text_layers(
            erased,
            outline_mask,
            fill_mask,
            mask,
            layers,
            outline_coverage_maximum=255,
        )

        self.assertEqual(
            default_audit["indexed_layer_counts"]["outline"],
            {"2": 1, "7": 1},
        )
        self.assertEqual(
            fixed_audit["indexed_layer_counts"]["outline"],
            {"1": 2},
        )
        self.assertEqual(fixed_indexes[0], 1)
        self.assertEqual(fixed_indexes[1], 1)
        self.assertEqual(
            fixed_audit["outline_coverage_normalization"],
            "absolute_locked",
        )

        with self.assertRaises(UiAtlasLocalizationError):
            apply_indexed_text_layers(
                erased,
                outline_mask,
                fill_mask,
                mask,
                layers,
                outline_coverage_maximum=11,
            )

    def test_indexed_shadow_uses_darkest_outline_role_one_pixel_down(self) -> None:
        mask = AtlasMask.from_mapping(
            {
                "x": 0,
                "y": 0,
                "width": 3,
                "height": 2,
                "replacement_rgba": "00000000",
                "preserve_rgba": ["00000000"],
            }
        )
        erased = bytes(CANARY_WIDTH * CANARY_HEIGHT * 4)
        outline_mask = bytes((255, 255, 0, 0, 0, 0))
        fill_mask = bytes((0, 255, 0, 0, 0, 0))
        layers = {
            "outline": (
                (bytes((16, 16, 16, 0xFF)), 1),
                (bytes((112, 112, 112, 0xFF)), 7),
            ),
            "fill": (
                (bytes((16, 16, 16, 0xFF)), 9),
                (bytes((112, 112, 112, 0xFF)), 15),
            ),
        }

        _rgba, audit, indexes = apply_indexed_text_layers(
            erased,
            outline_mask,
            fill_mask,
            mask,
            layers,
            shadow_offset=(0, 1),
        )

        self.assertEqual(indexes[CANARY_WIDTH], 1)
        self.assertEqual(indexes[CANARY_WIDTH + 1], 1)
        self.assertEqual(audit["shadow_offset"], {"x": 0, "y": 1})
        self.assertEqual(audit["shadow_palette_index"], 1)
        self.assertEqual(audit["shadow_pixel_count"], 2)

    def test_bazaar_group_headings_use_the_dedicated_palette_profile(self) -> None:
        config = json.loads(
            (
                PROJECT_ROOT / "config/assets/ui-bazaar-atlas-zh.json"
            ).read_text(encoding="utf-8")
        )
        profile = config["indexed_text_layer_profiles"][
            "bazaar-group-heading"
        ]
        self.assertEqual(
            [entry["palette_index"] for entry in profile["outline"]],
            list(range(1, 8)),
        )
        self.assertEqual(
            [entry["palette_index"] for entry in profile["fill"]],
            list(range(9, 16)),
        )

        targets = {
            "強化パーツ": ("ui-atlas/kvm5/parts", -2),
            "アイテム": ("ui-atlas/kvm5/items", -9),
            "機体": ("ui-atlas/kvm5/unit", 0),
        }
        labels = {
            entry["semantic_locator"]: entry
            for entry in config["additional_localized_labels"]
            if entry["semantic_locator"] in targets
        }
        self.assertEqual(set(labels), set(targets))
        for locator, (entry_id, horizontal_offset) in targets.items():
            self.assertEqual(labels[locator]["entry_id"], entry_id)
            render = labels[locator]["render"]
            self.assertEqual(render["point_size"], 17)
            self.assertEqual(render["stroke_width"], 1.5)
            self.assertEqual(
                render.get("horizontal_offset", 0),
                horizontal_offset,
            )
            self.assertEqual(render["vertical_offset"], -1)
            self.assertEqual(
                render["indexed_layer_profile"],
                "bazaar-group-heading",
            )
            self.assertEqual(
                render["indexed_outline_coverage_maximum"],
                255,
            )
            self.assertEqual(
                render["indexed_shadow_offset"],
                {"x": 0, "y": 1},
            )


if __name__ == "__main__":
    unittest.main()
