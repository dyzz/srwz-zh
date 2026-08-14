import hashlib
import json
import unittest
from dataclasses import asdict
from pathlib import Path

from tools.srwz.stage_formations import (
    FormationCell,
    FormationGroup,
    _scan_known_formation_slots,
    _scan_known_record_slots,
    _scan_packed8_groups,
    _scan_structural_formation_groups,
    _scan_structural_record_groups,
    formation_inventory_sha256,
    compact_formation_ascii_replacement,
    fit_formation_replacement,
    load_locked_stage_default_formations,
)
from tools.srwz.text import encode_text, load_text_table


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG = PROJECT_ROOT / "config/full-story-components.json"


class StageDefaultFormationTests(unittest.TestCase):
    def test_known_record_scan_keeps_single_owned_record(self):
        table = load_text_table(
            PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
        )
        source = "グローリー・スター１"
        encoded = encode_text(source, table, terminate=True)
        data = bytes.fromhex("000000000000")
        data += encoded + bytes(23 - len(encoded))

        group = _scan_known_record_slots(
            data,
            table,
            stage_index=2,
            source_texts=frozenset({source}),
        )

        self.assertIsNotNone(group)
        assert group is not None
        self.assertEqual(group.layout, "record6+23")
        self.assertEqual([cell.offset for cell in group.cells], [6])
        self.assertEqual(group.cells[0].prefix_hex, "000000000000")

    def test_known_record_scan_does_not_depend_on_next_leader_type(self):
        table = load_text_table(
            PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
        )
        source = "シベ鉄警備隊"
        encoded = encode_text(source, table, terminate=True)
        slot = encoded + bytes(23 - len(encoded))
        data = bytes.fromhex("00000000000c") + slot
        data += bytes.fromhex("000616030001") + slot

        group = _scan_known_record_slots(
            data,
            table,
            stage_index=14,
            source_texts=frozenset({source}),
        )

        self.assertIsNotNone(group)
        assert group is not None
        self.assertEqual(group.layout, "record6+23")
        self.assertEqual([cell.offset for cell in group.cells], [6, 35])
        self.assertEqual(
            [cell.prefix_hex for cell in group.cells],
            ["00000000000c", "000616030001"],
        )

    def test_structural_scan_requires_adjacent_owned_records(self):
        table = load_text_table(
            PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
        )
        source = "シベ鉄警備隊"
        encoded = encode_text(source, table, terminate=True)
        slot = encoded + bytes(23 - len(encoded))
        record = bytes.fromhex("00000000000c") + slot

        self.assertEqual(
            _scan_structural_record_groups(record, table, stage_index=14),
            (),
        )
        groups = _scan_structural_record_groups(
            record + bytes.fromhex("000616030001") + slot,
            table,
            stage_index=14,
        )
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0].cells), 2)

    def test_formation_table_scan_locks_members_metadata_and_trailer(self):
        table = load_text_table(
            PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
        )
        names = ("グローリー・スター", "マジンガーチーム")
        records = []
        for index, source in enumerate(names):
            member_ids = bytes.fromhex(
                "000100020003ffffffffffff"
            )
            metadata = bytes.fromhex("000102030405")
            encoded = encode_text(source, table, terminate=True)
            slot = encoded + bytes(33 - len(encoded))
            records.append(member_ids + metadata + slot + bytes([index]))

        self.assertEqual(
            _scan_structural_formation_groups(
                records[0], table, stage_index=50
            ),
            (),
        )
        groups = _scan_structural_formation_groups(
            b"".join(records), table, stage_index=50
        )
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].layout, "formation18+33+1")
        self.assertEqual([cell.offset for cell in groups[0].cells], [18, 70])
        self.assertEqual(
            [cell.trailer_hex for cell in groups[0].cells], ["00", "01"]
        )
        self.assertTrue(
            all(len(bytes.fromhex(cell.prefix_hex)) == 18 for cell in groups[0].cells)
        )

    def test_known_formation_scan_keeps_single_owned_record(self):
        table = load_text_table(
            PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
        )
        source = "ザフト"
        encoded = encode_text(source, table, terminate=True)
        prefix = bytes.fromhex("000100020003ffffffffffff000102030405")
        data = prefix + encoded + bytes(33 - len(encoded)) + b"\x07"

        group = _scan_known_formation_slots(
            data,
            table,
            stage_index=33,
            source_texts=frozenset({source}),
        )

        self.assertIsNotNone(group)
        assert group is not None
        self.assertEqual(group.layout, "formation18+33+1")
        self.assertEqual([cell.offset for cell in group.cells], [18])
        self.assertEqual(group.cells[0].prefix_hex, prefix.hex())
        self.assertEqual(group.cells[0].trailer_hex, "07")

    def test_known_formation_scan_keeps_bridged_sentinel_records(self):
        table = load_text_table(
            PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
        )
        source = "ザフト"
        encoded = encode_text(source, table, terminate=True)
        slot = encoded + bytes(33 - len(encoded))
        strict_members = bytes.fromhex("000100020003ffffffffffff")
        sentinel_members = bytes.fromhex("800180028003800480058006")
        metadata = bytes.fromhex("000102030405")
        records = [
            members + metadata + slot + bytes([index])
            for index, members in enumerate(
                (
                    strict_members,
                    sentinel_members,
                    sentinel_members,
                    strict_members,
                )
            )
        ]

        group = _scan_known_formation_slots(
            b"".join(records),
            table,
            stage_index=33,
            source_texts=frozenset({source}),
        )

        self.assertIsNotNone(group)
        assert group is not None
        self.assertEqual(
            [cell.offset for cell in group.cells],
            [18, 70, 122, 174],
        )

    def test_packed8_scan_keeps_adjacent_variable_size_fields(self):
        table = load_text_table(
            PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
        )
        sources = ("ザフト", "エゥーゴ", "グローリー・スター２")
        slots = []
        for source in sources:
            encoded = encode_text(source, table, terminate=True)
            slot_size = (len(encoded) + 7) // 8 * 8
            slots.append(encoded + bytes(slot_size - len(encoded)))

        groups = _scan_packed8_groups(
            b"".join(slots),
            table,
            stage_index=4,
            source_texts=frozenset(sources),
        )

        cells = {
            (group.layout, cell.offset, cell.source_text)
            for group in groups
            for cell in group.cells
        }
        self.assertEqual(
            cells,
            {
                ("packed8-8", 0, "ザフト"),
                ("packed8-16", 8, "エゥーゴ"),
                ("packed8-24", 24, "グローリー・スター２"),
            },
        )

    def test_packed8_zaft_uses_reviewed_compact_ascii(self):
        self.assertEqual(
            fit_formation_replacement(
                source_text="ザフト",
                translation="ZAFT",
                layout="packed8-8",
                slot_size=8,
                encoded=bytes(9),
            ),
            b"ZAFT\x00\x00\x00\x00",
        )
        self.assertEqual(
            compact_formation_ascii_replacement(
                source_text="ザフト",
                translation="ZAFT",
                layout="packed8-8",
                slot_size=8,
            ),
            b"ZAFT\x00\x00\x00\x00",
        )
    def test_reviewed_global_term_asset_is_locked(self):
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        reference = config["remaining_ui"]["stage_default_formations"]
        payload = (PROJECT_ROOT / reference["path"]).read_bytes()
        self.assertEqual(len(payload), reference["size"])
        self.assertEqual(hashlib.sha256(payload).hexdigest(), reference["sha256"])

        document = json.loads(payload.decode("utf-8"))
        terms = document["translations_by_source_text"]
        self.assertEqual(document["editorial_status"], "reviewed")
        self.assertEqual(
            document["policy"]["build_selection_authority"],
            "locked_occurrence_inventory",
        )
        self.assertTrue(
            document["policy"]["scan_only_when_explicitly_refreezing"]
        )
        self.assertTrue(document["policy"]["require_locked_source_coverage"])
        self.assertTrue(document["policy"]["preserve_record_metadata"])
        self.assertEqual(len(terms), 248)
        self.assertEqual(terms["エゥーゴ"], "奥古")
        self.assertEqual(terms["グローリー・スター１"], "荣耀之星1")
        self.assertEqual(terms["ザフト"], "ZAFT")
        self.assertEqual(
            document["accepted_current_translations_by_source_text"],
            {"Ｇソルジャー": ["G-Soldier"]},
        )
        self.assertEqual(terms["ザンベース"], "桑贝斯")
        self.assertEqual(terms["シベ鉄警備隊"], "西伯铁警备队")
        self.assertEqual(terms["アデット隊"], "亚蒂特队")
        self.assertEqual(terms["ギンガナム艦隊"], "金卡拉姆舰队")
        self.assertEqual(terms["セント・レーガン"], "圣雷根")
        self.assertEqual(terms["マジンガーチーム"], "魔神小队")
        self.assertEqual(terms["サンドラット"], "沙鼠团")
        self.assertEqual(terms["ダイナミックチーム"], "豪烈小队")
        self.assertEqual(terms["フリーデン隊"], "和平号队")
        self.assertEqual(terms["黒いサザンクロス"], "黑色南十字星")

    def test_reviewed_sources_cover_every_locked_position(self):
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        remaining = config["remaining_ui"]
        reference = remaining["stage_default_formations"]
        terms = json.loads(
            (PROJECT_ROOT / reference["path"]).read_text(encoding="utf-8")
        )["translations_by_source_text"]
        inventory_reference = remaining["stage_default_formation_inventory"]
        inventory_payload = (
            PROJECT_ROOT / inventory_reference["path"]
        ).read_bytes()
        self.assertEqual(len(inventory_payload), inventory_reference["size"])
        self.assertEqual(
            hashlib.sha256(inventory_payload).hexdigest(),
            inventory_reference["sha256"],
        )
        inventory = json.loads(inventory_payload.decode("utf-8"))
        groups = load_locked_stage_default_formations(
            (PROJECT_ROOT / remaining["original_stage"]["path"]).read_bytes(),
            (PROJECT_ROOT / config["full_story_stage"]["hb"]["path"]).read_bytes(),
            load_text_table(
                PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
            ),
            inventory,
        )
        locked_sources = {
            cell.source_text for group in groups for cell in group.cells
        }
        self.assertEqual(set(terms), locked_sources)
        self.assertEqual(len(groups), 794)
        self.assertEqual(sum(len(group.cells) for group in groups), 11170)
        female_stage_1 = {
            (cell.offset, cell.source_text)
            for group in groups
            if group.stage_index == 1
            for cell in group.cells
        }
        female_stage_2 = {
            (cell.offset, cell.source_text)
            for group in groups
            if group.stage_index == 2
            for cell in group.cells
        }
        self.assertTrue(
            {
                (45744, "グローリー・スター１"),
                (45776, "グローリー・スター２"),
                (45808, "グローリー・スター３"),
            }
            <= female_stage_1
        )
        self.assertTrue(
            {
                (33361, "ザフト"),
                (33796, "ザフト"),
                (74928, "グローリー・スター１"),
                (74960, "グローリー・スター２"),
                (74992, "グローリー・スター３"),
            }
            <= female_stage_2
        )
        self.assertFalse(
            {
                (14, 0xC328),
                (16, 0xD988),
                (138, 0x2A6C0),
            }
            & {
                (group.stage_index, cell.offset)
                for group in groups
                for cell in group.cells
            }
        )
        packed_positions = {
            (group.stage_index, cell.offset, cell.source_text)
            for group in groups
            if group.layout.startswith("packed8-")
            for cell in group.cells
        }
        self.assertIn((4, 0x12348, "ザフト"), packed_positions)
        self.assertIn((6, 0xE800, "グローリー・スター２"), packed_positions)
        self.assertNotIn((59, 0x1B90, "ザフト"), packed_positions)
        self.assertIn((107, 0x25F08, "Ｇソルジャー"), packed_positions)
        self.assertEqual(inventory["scan_policy"], "explicit_refreeze_only")

    def test_inventory_hash_locks_order_sources_and_metadata(self):
        groups = (
            FormationGroup(
                stage_index=2,
                layout="record23+6",
                slot_size=23,
                stride=29,
                cells=(
                    FormationCell(100, "ザフト", 7, "00020d03000c"),
                    FormationCell(129, "ザフト", 7, "00020d030000"),
                ),
            ),
        )
        payload = json.dumps(
            [asdict(group) for group in groups],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.assertEqual(
            formation_inventory_sha256(groups),
            hashlib.sha256(payload).hexdigest(),
        )
        changed = (
            FormationGroup(
                stage_index=2,
                layout="record23+6",
                slot_size=23,
                stride=29,
                cells=(
                    FormationCell(100, "ザフト", 7, "00020d03000c"),
                    FormationCell(129, "ザフト", 7, "00020d030004"),
                ),
            ),
        )
        self.assertNotEqual(
            formation_inventory_sha256(groups),
            formation_inventory_sha256(changed),
        )


if __name__ == "__main__":
    unittest.main()
