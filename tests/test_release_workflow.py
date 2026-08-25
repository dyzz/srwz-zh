from __future__ import annotations

import base64
import hashlib
import json
import unittest
import zlib
from pathlib import Path

from tools.build_full_story_components import (
    ALL_COMPONENT_MEMBERS,
    COMPONENT_BUILD_GROUPS,
)
from tools.srwz.title_menu import (
    RAMP_LEVEL_COUNT,
    SELECTED_RAMP_BASE,
    TITLE_LABEL_HEIGHT,
    TITLE_LABEL_WIDTH,
    TITLE_TEXTURE_HEIGHT,
    TITLE_TEXTURE_WIDTH,
    UNSELECTED_RAMP_BASE,
    apply_title_menu_masks,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load(relative: str) -> dict:
    return json.loads((PROJECT_ROOT / relative).read_text(encoding="utf-8"))


def _mapping_sha256(assignments: list[dict]) -> str:
    rows = sorted(
        (item["character"], item["code"], item["glyph_index"])
        for item in assignments
    )
    return hashlib.sha256(
        json.dumps(
            rows,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


class ReleaseWorkflowTest(unittest.TestCase):
    def test_chapter_intertitles_keep_linear_index_storage(self) -> None:
        corpus = _load("corpus/zh/chapter-intertitles.json")
        self.assertEqual(
            corpus["render"]["storage_layout"],
            "linear_row_major_despite_psmt8_header",
        )
        self.assertEqual(
            corpus["visible_japanese_text_chunk_indices"],
            [21, 22],
        )
        for entry in corpus["entries"]:
            self.assertIn("source_linear_indexes_sha256", entry)
            self.assertIn("output_linear_indexes_sha256", entry)
            self.assertNotIn("source_logical_indexes_sha256", entry)
            self.assertNotIn("output_logical_indexes_sha256", entry)

    def test_bazaar_status_labels_preserve_original_pixels(self) -> None:
        config = _load("config/assets/ui-bazaar-atlas-zh.json")
        corpus = _load("corpus/zh/ui-atlas/bazaar-v2.json")
        decisions = {entry["id"]: entry for entry in corpus["entries"]}
        labels = {
            entry["entry_id"]: entry
            for entry in config["additional_localized_labels"]
        }
        self.assertEqual(
            (
                decisions["ui-atlas/kvm5/funds"]["source_text"],
                decisions["ui-atlas/kvm5/funds"]["translation"],
                labels["ui-atlas/kvm5/funds"]["mask"],
            ),
            ("資", "資", {
                "x": 209,
                "y": 2,
                "width": 20,
                "height": 20,
                "replacement_rgba": "00000000",
                "preserve_rgba": ["00000000"],
            }),
        )
        self.assertEqual(
            (
                decisions["ui-atlas/kvm5/sr-points"]["source_text"],
                decisions["ui-atlas/kvm5/sr-points"]["translation"],
                labels["ui-atlas/kvm5/sr-points"]["mask"],
            ),
            ("ポイント", "点数", {
                "x": 174,
                "y": 42,
                "width": 53,
                "height": 21,
                "replacement_rgba": "00000000",
                "preserve_rgba": ["00000000"],
            }),
        )
        snapshot = _load(
            "config/assets/ui-bazaar-atlas-render-snapshot.json"
        )
        frozen = {
            entry["entry_id"]: entry for entry in snapshot["labels"]
        }
        funds_template = frozen["ui-atlas/kvm5/funds"][
            "template_provenance"
        ]
        points_template = frozen["ui-atlas/kvm5/sr-points"][
            "template_provenance"
        ]
        self.assertEqual(
            funds_template["selection_authority"],
            "original_japanese_texture_pixel_exact_user_requested",
        )
        self.assertEqual(funds_template["exact_original_rows"], 20)
        self.assertEqual(
            points_template["glyphs"],
            [
                {"character": "点", "glyph_index": 3487},
                {"character": "数", "glyph_index": 2964},
            ],
        )
        self.assertEqual(
            points_template["placement"],
            {
                "mask_width": 53,
                "mask_height": 21,
                "cell_width": 20,
                "cell_height": 20,
                "left_offsets": [6, 27],
                "top_offset": 0,
            },
        )
        self.assertEqual(
            sum(
                count
                for index, count in funds_template[
                    "logical_index_counts"
                ].items()
                if 1 <= int(index) <= 7
            ),
            224,
        )
        self.assertEqual(
            sum(
                count
                for index, count in points_template[
                    "logical_index_counts"
                ].items()
                if 8 <= int(index) <= 15
            ),
            243,
        )
        self.assertTrue(funds_template["source_palette_histogram_exact"])
        self.assertTrue(points_template["source_palette_histogram_exact"])

    def test_every_component_member_has_one_build_group(self) -> None:
        members = [
            member
            for group in COMPONENT_BUILD_GROUPS
            for member in group["members"]
        ]
        self.assertEqual(len(members), len(set(members)))
        self.assertEqual(set(members), set(ALL_COMPONENT_MEMBERS))
        self.assertEqual(
            [group["id"] for group in COMPONENT_BUILD_GROUPS],
            [
                "core_runtime_members",
                "localized_data_members",
                "rendered_archive_members",
            ],
        )

    def test_release_menu_selection_is_source_bound_and_unique(self) -> None:
        corpus = _load("corpus/zh/menu/release-v0.3.json")
        entries = corpus["entries"]
        expected = corpus["expected"]
        self.assertEqual(corpus["release_id"], "v0.3.0")
        self.assertEqual(
            corpus["selection_authority"],
            "manual_v0.3.0_release_selection",
        )
        self.assertFalse(corpus["release_evidence"]["build_dependency"])
        self.assertEqual(len(entries), expected["entry_count"])
        self.assertEqual(len({entry["id"] for entry in entries}), len(entries))
        entry_by_id = {entry["id"]: entry for entry in entries}
        self.assertEqual(
            entry_by_id["menu/SLPS/00/0343"]["translation"],
            "%s%s",
        )
        self.assertEqual(
            entry_by_id["menu/SLPS/00/0343"]["target_count"],
            2,
        )
        self.assertTrue(
            all(
                len(entry["source_text_sha256"]) == 64
                and entry["target_count"] > 0
                for entry in entries
            )
        )
        member_counts = {
            member: sum(entry["member"] == member for entry in entries)
            for member in ("SLPS", "Compdata")
        }
        self.assertEqual(member_counts, expected["member_entry_counts"])
        raw_ascii_entries = [
            entry for entry in entries if "raw_ascii_characters" in entry
        ]
        self.assertEqual(
            len(raw_ascii_entries),
            expected["raw_ascii_compatible_entry_count"],
        )
        self.assertEqual(raw_ascii_entries[0]["raw_ascii_characters"], "Yo")

    def test_release_menu_codebook_is_one_to_one(self) -> None:
        codebook = _load("config/encoding/release-menu-codebook.json")
        assignments = codebook["assignments"]
        self.assertEqual(codebook["codebook_id"], "srwz-release-menu-v0.3")
        self.assertEqual(len(assignments), codebook["assignment_count"])
        self.assertEqual(
            len({item["character"] for item in assignments}),
            len(assignments),
        )
        self.assertEqual(
            len({item["code"] for item in assignments}),
            len(assignments),
        )
        self.assertEqual(
            len({item["glyph_index"] for item in assignments}),
            len(assignments),
        )
        self.assertEqual(_mapping_sha256(assignments), codebook["mapping_sha256"])

    def test_title_menu_contract_and_eight_slots_are_deterministic(self) -> None:
        contract = _load("config/assets/title-menu-zh.json")
        self.assertEqual(contract["status"], "reviewed_locked")
        self.assertEqual(
            [label["translation"] for label in contract["labels"]],
            ["开始", "读取", "继续", "资料库"],
        )
        masks = []
        for frozen in contract["masks"]:
            mask = zlib.decompress(base64.b64decode(frozen["zlib_base64"]))
            self.assertEqual(len(mask), frozen["size"])
            self.assertEqual(hashlib.sha256(mask).hexdigest(), frozen["sha256"])
            masks.append(mask)

        original = bytes(TITLE_TEXTURE_WIDTH * TITLE_TEXTURE_HEIGHT)
        output, slots = apply_title_menu_masks(original, masks)
        self.assertEqual(len(output), len(original))
        self.assertEqual(len(slots), 8)
        self.assertEqual(
            [slot["y"] for slot in slots],
            [index * TITLE_LABEL_HEIGHT for index in range(8)],
        )
        for slot in slots:
            ramp_base = (
                SELECTED_RAMP_BASE
                if slot["state"] == "selected"
                else UNSELECTED_RAMP_BASE
            )
            start = slot["y"] * TITLE_TEXTURE_WIDTH
            rows = b"".join(
                output[
                    start
                    + row * TITLE_TEXTURE_WIDTH : start
                    + row * TITLE_TEXTURE_WIDTH
                    + TITLE_LABEL_WIDTH
                ]
                for row in range(TITLE_LABEL_HEIGHT)
            )
            self.assertTrue(
                all(ramp_base <= value < ramp_base + RAMP_LEVEL_COUNT for value in rows)
            )


if __name__ == "__main__":
    unittest.main()
