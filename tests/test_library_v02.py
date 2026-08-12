import json
import struct
import unittest
from pathlib import Path

from tools.srwz.library import (
    LibraryScopeError,
    SoundTitleSpanLock,
    build_runtime_zkn_decoded_chunk,
    parse_runtime_zkn_decoded_chunk,
    parse_zkn_decoded_chunk,
    parse_sound_track_titles,
    verify_sound_titles_preserved,
    validate_library_scope_mapping,
    zkan_escape_transform,
)
from tools.srwz.text import TextTable, load_text_table


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config/library/v0.2.0.json"
RELEASE_PATH = PROJECT_ROOT / "corpus/releases/v2.json"
TEXT_TABLE = PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"


class LibraryV02Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cls.release = json.loads(RELEASE_PATH.read_text(encoding="utf-8"))
        cls.table = load_text_table(TEXT_TABLE)

    def test_release_scope_includes_all_library_surfaces(self):
        validate_library_scope_mapping(self.config)
        self.assertEqual(self.config["release"], "0.2.0")
        self.assertEqual(self.config["decision"], "include_complete_library")
        self.assertEqual(
            {surface["id"] for surface in self.config["surfaces"]},
            {
                "library-menu",
                "robot-encyclopedia",
                "character-encyclopedia",
                "glossary",
                "sound-select",
                "scenario-chart",
                "strategy-qa",
            },
        )

    def test_sound_track_titles_are_excluded_from_translation(self):
        sound = self.config["sound_select"]
        self.assertEqual(
            sound["track_title_policy"],
            "preserve_original_japanese_byte_exact",
        )
        self.assertIs(sound["track_titles_in_translation_corpus"], False)
        self.assertTrue(self.release["translation_sources"])
        self.assertTrue(
            all(
                source.get("promoted_to_corpus") is True
                for source in self.release["translation_sources"]
            )
        )
        self.assertEqual(
            self.release["translation_sources"][0]["reviewed_corpus"],
            "corpus/zh/library/v0.2-reviewed.json",
        )
        self.assertIs(
            self.release["review_policy"][
                "sound_track_titles_are_not_translation_entries"
            ],
            True,
        )
        protected = self.release["protected_source_ranges"]
        self.assertEqual(len(protected), 1)
        self.assertEqual(
            protected[0]["policy"],
            "preserve_original_japanese_byte_exact",
        )

    def test_v2_corpus_manifest_tracks_every_scope_batch(self):
        self.assertEqual(self.release["version"], "0.2.0")
        self.assertEqual(self.release["status"], "in_progress")
        self.assertEqual(
            {batch["batch_id"] for batch in self.release["coverage_plan"]},
            {
                "v2-library-menu",
                "v2-robot-encyclopedia",
                "v2-character-encyclopedia",
                "v2-glossary",
                "v2-sound-select-ui",
                "v2-scenario-chart",
                "v2-strategy-qa",
            },
        )

    def test_translation_model_is_locked_to_fixed_snapshot(self):
        lock = self.config["translation_model_lock"]
        self.assertEqual(lock["model"], "deepseek-v4-flash-0731")
        self.assertEqual(lock["policy"], "fixed_snapshot_required")
        self.assertIs(lock["rolling_alias_allowed"], False)
        source = self.release["translation_sources"][0]
        self.assertEqual(source["model"], lock["model"])
        self.assertEqual(source["model_policy"], "fixed_snapshot")

    def test_sound_title_parser_and_byte_exact_gate(self):
        source = bytearray(0x80)
        source[0x20:0x25] = b"ONE\0\0"
        source[0x28:0x2D] = b"TWO\0\0"
        lock_raw = {
            "start": 0x20,
            "end": 0x40,
            "alignment": 8,
            "expected_title_count": 2,
            "expected_span_sha256": "0" * 64,
        }
        lock = SoundTitleSpanLock.from_mapping(lock_raw)
        entries = parse_sound_track_titles(bytes(source), self.table, lock)
        self.assertEqual([entry.text for entry in entries], ["ONE", "TWO"])

        candidate = bytes(source)
        verify_sound_titles_preserved(bytes(source), candidate, lock)

        changed = bytearray(source)
        changed[0x29] = ord("A")
        with self.assertRaisesRegex(
            LibraryScopeError, "changed in candidate.*0x29"
        ):
            verify_sound_titles_preserved(bytes(source), bytes(changed), lock)

    def test_rejects_malformed_sound_title_lock(self):
        raw = {
            "start": 0x21,
            "end": 0x40,
            "alignment": 8,
            "expected_title_count": 2,
            "expected_span_sha256": "0" * 64,
        }
        with self.assertRaisesRegex(LibraryScopeError, "alignment"):
            SoundTitleSpanLock.from_mapping(raw)

    def test_zkan_escape_transform_is_involutory(self):
        source = bytes(range(256))
        encoded = zkan_escape_transform(source)
        self.assertEqual(encoded[0], 0)
        self.assertEqual(encoded[0x5E], 0x5E)
        self.assertEqual(zkan_escape_transform(encoded), source)

    def test_parses_wrapped_zkan_keyword_document(self):
        fields = [
            ("WORD", "ティターンズ"),
            ("SRCE", "機動戦士Ｚガンダム"),
            ("DSCR", "地球出身のエリートで構成された特殊部隊。"),
            ("DSC2", "地球出身のエリートで構成された特殊部隊。"),
        ]
        data = bytearray()
        for tag, text in fields:
            encoded = text.encode("cp932")
            data.extend(tag.encode("ascii"))
            data.extend(struct.pack("<I", len(encoded)))
            data.extend(encoded)
        payload = bytearray(b"ZKANKYWD")
        payload.extend(struct.pack("<I", 0x100))
        payload.extend(struct.pack("<I", 0x0C))
        payload.extend(b"DSIZ")
        payload.extend(struct.pack("<I", len(data) + 8))
        payload.extend(b"DATA")
        payload.extend(struct.pack("<I", len(data)))
        payload.extend(data)
        escaped = zkan_escape_transform(bytes(payload))
        wrapper = struct.pack(
            "<8I", 1, 0x20, 0, len(escaped), len(escaped), 0, 0, 0
        )

        document = parse_zkn_decoded_chunk(wrapper + escaped)

        self.assertEqual(document.kind, "KYWD")
        self.assertEqual(document.version, 0x100)
        self.assertEqual(document.field("WORD").text, "ティターンズ")
        self.assertEqual(document.field("DSCR").text, fields[2][1])

    def test_zkan_parser_rejects_unknown_field(self):
        raw = b"JUNK" + struct.pack("<I", 0)
        payload = (
            b"ZKANKYWD"
            + struct.pack("<II", 0x100, 0x0C)
            + b"DSIZ"
            + struct.pack("<I", len(raw) + 8)
            + b"DATA"
            + struct.pack("<I", len(raw))
            + raw
        )
        escaped = zkan_escape_transform(payload)
        wrapper = struct.pack(
            "<8I", 1, 0x20, 0, len(escaped), len(escaped), 0, 0, 0
        )
        with self.assertRaisesRegex(LibraryScopeError, "unsupported ZKAN field"):
            parse_zkn_decoded_chunk(wrapper + escaped)

    def test_localized_zkan_build_and_runtime_reread(self):
        fields = [
            ("WORD", "原語"),
            ("SRCE", "作品"),
            ("DSCR", "説明"),
            ("DSC2", "説明"),
        ]
        data = bytearray()
        for tag, text in fields:
            encoded = text.encode("cp932")
            data.extend(tag.encode("ascii"))
            data.extend(struct.pack("<I", len(encoded)))
            data.extend(encoded)
        payload = (
            b"ZKANKYWD"
            + struct.pack("<II", 0x100, 0x0C)
            + b"DSIZ"
            + struct.pack("<I", len(data) + 8)
            + b"DATA"
            + struct.pack("<I", len(data))
            + bytes(data)
        )
        escaped = zkan_escape_transform(payload)
        wrapper = struct.pack(
            "<8I", 1, 0x20, 0, len(escaped), len(escaped), 0, 0, 0
        )
        source = parse_zkn_decoded_chunk(wrapper + escaped)
        table = TextTable(
            characters={
                0x889F: "中",
                0x88A0: "文",
                0x88A1: "机",
                0x88A2: "体",
            },
            tags={},
        )
        localized = build_runtime_zkn_decoded_chunk(
            source,
            table,
            {"WORD": "中", "SRCE": "文", "DSCR": "机", "DSC2": "体"},
        )
        self.assertEqual(len(localized) % 16, 0)
        reread = parse_runtime_zkn_decoded_chunk(localized, table)
        self.assertEqual(reread.kind, "KYWD")
        self.assertEqual(reread.field("WORD").text, "中")
        self.assertEqual(reread.field("DSC2").text, "体")


if __name__ == "__main__":
    unittest.main()
