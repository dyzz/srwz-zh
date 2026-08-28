from __future__ import annotations

import base64
import hashlib
import json
import struct
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
from tools.srwz.stage import STAGE_BASE_ADDRESS
from tools.srwz.stage_formations import _scan_packed8_groups
from tools.srwz.text import encode_text, load_text_table
from tools.srwz.release_font import (
    audit_entry_font,
    baseline_with_protected_original_glyphs,
)
from tools.srwz.font import GLYPH_SIZE, standard_glyph_index
from tools.srwz.chinese_layout import (
    dialogue_line_widths,
    fit_chinese_dialogue_layout,
    logical_dialogue_text,
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
    def test_dialogue_layout_reflows_without_shortening_text(self) -> None:
        source = "“我们也对迪兰达尔议长的所作所为心存疑虑。”"
        fitted = fit_chinese_dialogue_layout(source)
        self.assertEqual(fitted.preserved_reason, "reflowed_to_fit")
        self.assertEqual(
            logical_dialogue_text(fitted.text),
            logical_dialogue_text(source),
        )
        self.assertLessEqual(len(fitted.line_widths), 3)
        self.assertLessEqual(max(fitted.line_widths), 21)

    def test_dialogue_layout_preserves_valid_manual_breaks(self) -> None:
        source = "“第一行。”\n　第二行。”"
        fitted = fit_chinese_dialogue_layout(source)
        self.assertEqual(fitted.preserved_reason, "already_fits")
        self.assertEqual(fitted.text, source)
        self.assertEqual(fitted.line_widths, dialogue_line_widths(source))

    def test_protected_stock_punctuation_is_valid_localized_text(self) -> None:
        class Table:
            inverse_characters = {"」": 0x8176}
            characters = {0x8176: "」"}

        baseline = {
            "table": Table(),
            "extended_entries": (),
            "font": b"\x01" * (
                (standard_glyph_index(0x8176) + 1) * GLYPH_SIZE
            ),
            "base_assignments": {},
            "proposal_assignments": {},
        }
        protected = baseline_with_protected_original_glyphs(
            baseline,
            {
                "protected_source_characters": "」",
                "protected_original_codes": ["8176"],
            },
        )
        coverage = audit_entry_font(
            [{"id": "bazaar", "translation": "」"}],
            protected,
        )
        self.assertEqual(coverage["missing_character_count"], 0)
        self.assertEqual(coverage["original_font_visible_character_count"], 0)
        self.assertEqual(coverage["selected_font_visible_character_count"], 1)

    def test_bazaar_confirmation_fragments_keep_corner_brackets(self) -> None:
        remaining = _load("corpus/zh/menu/remaining-ui.json")
        fragments = remaining["slps_context_ui_by_offset"]
        self.assertEqual(fragments["0x33DA60"], "」将被购买。")
        self.assertEqual(fragments["0x33DA98"], "」售　")

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

    def test_short_formation_table_requires_its_owner_record(self) -> None:
        table = load_text_table(
            PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
        )
        source = "ファクトリー"
        text_offset = 64
        encoded = encode_text(source, table, terminate=True)
        data = bytearray(96)
        data[text_offset : text_offset + len(encoded)] = encoded

        self.assertEqual(
            _scan_packed8_groups(
                bytes(data),
                table,
                stage_index=23,
                source_texts=frozenset({source}),
            ),
            (),
        )

        # The 32-byte formation owner places its name pointer at byte 16.
        data[8:10] = b"\xFF\xFF"
        data[14:16] = b"\xFF\xFF"
        struct.pack_into("<I", data, 16, STAGE_BASE_ADDRESS + text_offset)
        struct.pack_into("<I", data, 20, 0xFF)
        groups = _scan_packed8_groups(
            bytes(data),
            table,
            stage_index=23,
            source_texts=frozenset({source}),
        )
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].layout, "pointer8-16")
        self.assertEqual(
            [(cell.offset, cell.source_text) for cell in groups[0].cells],
            [(text_offset, source)],
        )

    def test_formation_inventory_covers_all_26_new_owned_slots(self) -> None:
        corpus = _load("corpus/zh/menu/stage-default-formations.json")
        terms = corpus["translations_by_source_text"]
        self.assertEqual(len(terms), 256)
        self.assertEqual(terms["エゥーゴ１"], "奥古1")
        self.assertEqual(terms["アイアン・ギアー組"], "钢铁齿轮组")
        self.assertEqual(terms["アーサー親衛隊"], "阿瑟亲卫队")
        self.assertEqual(terms["ソレイユ（味方）"], "太阳号（我方）")
        self.assertEqual(terms["修理屋"], "修理工")
        self.assertEqual(terms["ガウリ隊"], "高富利队")

        inventory = _load("config/stage-default-formation-inventory.json")
        self.assertEqual(
            inventory["expected"],
            {
                "entry_count": 11424,
                "group_count": 828,
                "inventory_sha256": (
                    "32e53fa9b14fc39f41f4e08218e90585413f2dce5dd76ac203ce2c36ede9f013"
                ),
                "stage_count": 179,
                "unique_source_count": 256,
            },
        )

        sources = inventory["sources"]
        positions = {
            (group["stage_index"], offset): (sources[source_index], group["layout"])
            for group in inventory["groups"]
            for offset, source_index in group["cells"]
        }
        expected = {
            (9, 0xCF78): ("エゥーゴ２", "packed8-16"),
            (9, 0xCFA0): ("エゥーゴ１", "packed8-16"),
            (10, 0x15AA8): ("エゥーゴ１", "packed8-16"),
            (10, 0x15AB8): ("エゥーゴ２", "packed8-16"),
            (23, 0x7E10): ("ファクトリー", "pointer8-16"),
            (28, 0x1C8B8): ("グローマ隊", "packed8-16"),
            (28, 0x1C9C8): ("エクソダス組", "packed8-16"),
            (29, 0x13B68): ("　ゴッドシグマ", "packed8-24"),
            (31, 0xC510): ("カラバ", "pointer8-8"),
            (62, 0xD780): ("キング・ビアル", "pointer8-16"),
            (62, 0xD790): ("ゴッドシグマ", "pointer8-16"),
            (64, 0xA700): ("グランナイツ", "pointer8-16"),
            (65, 0xD158): ("キング・ビアル", "pointer8-16"),
            (65, 0xD168): ("グランナイツ", "pointer8-16"),
            (107, 0x25F30): ("アイアン・ギアー組", "packed8-32"),
            (108, 0x1BE40): ("アイアン・ギアー組", "packed8-32"),
            (108, 0x1BE78): ("アーサー親衛隊", "packed8-16"),
            (124, 0x17F0): ("フリーデン隊", "pointer8-16"),
            (137, 0x6F00): ("ソレイユ（味方）", "packed8-24"),
            (140, 0x1F2D8): ("ネゴシエイター", "pointer8-16"),
            (145, 0x18C40): ("ソレイユ（味方）", "packed8-32"),
            (159, 0xD10): ("ザンボット３", "pointer8-16"),
            (162, 0xA90): ("バルディオス", "pointer8-16"),
            (166, 0x1010): ("ニルヴァーシュ", "pointer8-16"),
            (169, 0x1D78): ("アクエリオン", "pointer8-16"),
            (170, 0x1CF8): ("アクエリオン", "pointer8-16"),
        }
        self.assertEqual(
            {position: positions.get(position) for position in expected},
            expected,
        )
        # This is runtime-keyword row 19, not a formation owner.
        self.assertNotIn((95, 0x106C8), positions)

    def test_gowri_name_is_consistent_across_current_corpus(self) -> None:
        glossary = _load("corpus/glossary/story-speakers-v1.json")
        entry = next(
            item
            for item in glossary["terms"]
            if item["id"] == "people/speaker-980ee4d20d74"
        )
        self.assertEqual(entry["translation"], "高富利")
        self.assertIn("高富力", entry["deprecated_translations"])

        stale_paths = [
            path.relative_to(PROJECT_ROOT).as_posix()
            for path in (PROJECT_ROOT / "corpus" / "zh").rglob("*.json")
            if "高富力" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(stale_paths, [])

    def test_repairer_labels_use_natural_chinese_person_term(self) -> None:
        paths = sorted((PROJECT_ROOT / "corpus/zh/story-dialogue").glob("*.json"))
        paths.append(PROJECT_ROOT / "corpus/zh/battle/srvc-lines.json")
        allowed_compounds = ("流浪的修理屋", "流浪修理屋")
        unexpected: list[str] = []
        preserved: set[str] = set()

        for path in paths:
            document = json.loads(path.read_text(encoding="utf-8"))
            for entry in document["entries"]:
                translation = entry.get("translation", "")
                if "修理屋" not in translation:
                    continue
                remainder = translation
                for compound in allowed_compounds:
                    if compound in translation:
                        preserved.add(entry["id"])
                    remainder = remainder.replace(compound, "")
                if "修理屋" in remainder:
                    unexpected.append(entry["id"])

        self.assertEqual(unexpected, [])
        self.assertEqual(
            preserved,
            {
                "story/014/dialogue/02.02/0073",
                "story/017/dialogue/01.06/0005",
                "story/024/dialogue/01.27/0005",
                "story/025/dialogue/02.01/0212",
                "story/026/dialogue/02.01/0121",
                "story/083/dialogue/01.17/0002",
                "story/111/dialogue/02.01/0273",
                "story/149/dialogue/01.35/0026",
                "story/150/dialogue/02.01/0363",
                "story/150/dialogue/02.01/0749",
                "story/150/dialogue/02.01/1142",
                "story/150/dialogue/02.01/1414",
                "story/150/dialogue/02.01/1433",
            },
        )

    def test_bazaar_status_labels_preserve_original_funds_texture(self) -> None:
        config = _load("config/assets/ui-bazaar-atlas-zh.json")
        corpus = _load("corpus/zh/ui-atlas/bazaar-v2.json")
        decisions = {entry["id"]: entry for entry in corpus["entries"]}
        labels = {
            entry["entry_id"]: entry
            for entry in config["additional_localized_labels"]
        }
        self.assertNotIn("ui-atlas/kvm5/funds", decisions)
        self.assertNotIn("ui-atlas/kvm5/funds", labels)
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
        self.assertNotIn("ui-atlas/kvm5/funds", frozen)
        points_template = frozen["ui-atlas/kvm5/sr-points"][
            "template_provenance"
        ]
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
                for index, count in points_template[
                    "logical_index_counts"
                ].items()
                if 8 <= int(index) <= 15
            ),
            243,
        )
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
