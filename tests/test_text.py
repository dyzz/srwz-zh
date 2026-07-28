import json
import unittest
from collections import Counter
from pathlib import Path

from tools.srwz.text import (
    SrwzTextEncodeError,
    SrwzTextError,
    augment_text_table,
    decode_text,
    encode_text,
    load_text_table,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_ROOT = PROJECT_ROOT / "vendor" / "upstream-python"
TEXT_TABLE = UPSTREAM_ROOT / "project" / "tbl_all.json"
TAG_FIXTURES = UPSTREAM_ROOT / "tools" / "python" / "tests" / "test_tags.json"


class TextDecodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.table = load_text_table(TEXT_TABLE)

    def test_pinned_table_shape(self):
        self.assertEqual(len(self.table.characters), 6860)
        self.assertEqual(
            dict(self.table.tags),
            {0x31: "color", 0x32: "width", 0x33: "height", 0x34: "space"},
        )

    def test_matches_all_upstream_control_code_fixtures(self):
        fixtures = json.loads(TAG_FIXTURES.read_text(encoding="utf-8"))
        # The pinned upstream decode test intentionally covers the first six.
        # Its seventh item exercises ASCII remapping in the separate encoder.
        for encoded, expected in list(fixtures.items())[:6]:
            with self.subTest(encoded=encoded):
                data = bytes.fromhex(encoded) + b"\x00"
                self.assertEqual(
                    decode_text(data, 0, self.table).text,
                    expected,
                )

    def test_speaker_mode_stops_at_newline(self):
        data = b"speaker\nmessage\x00"
        speaker = decode_text(data, 0, self.table, stop_at_newline=True)
        message = decode_text(data, speaker.end, self.table)
        self.assertEqual(speaker.text, "speaker")
        self.assertEqual(speaker.terminator, "newline")
        self.assertEqual(message.text, "message")

    def test_unknown_two_byte_code_is_lossless(self):
        decoded = decode_text(b"\x80\x00\x00", 0, self.table)
        self.assertEqual(decoded.text, "{80}{00}")
        self.assertEqual(decoded.unknown_code_count, 1)

    def test_rejects_truncated_two_byte_code(self):
        with self.assertRaises(SrwzTextError) as raised:
            decode_text(b"\x82", 0, self.table)
        self.assertEqual(raised.exception.offset, 1)

    def test_rejects_unterminated_text(self):
        with self.assertRaises(SrwzTextError) as raised:
            decode_text(b"abc", 0, self.table)
        self.assertEqual(raised.exception.offset, 3)

    def test_encode_round_trips_table_text_and_control_codes(self):
        text = "ＡBC\n<color:05>{1F}"
        encoded = encode_text(text, self.table, terminate=True)
        self.assertEqual(decode_text(encoded, 0, self.table).text, text)

    def test_encode_uses_lowest_duplicate_code_deterministically(self):
        counts = Counter(self.table.characters.values())
        duplicate = next(
            character
            for character in self.table.characters.values()
            if counts[character] > 1
        )
        codes = sorted(
            code
            for code, character in self.table.characters.items()
            if character == duplicate
        )
        self.assertEqual(
            encode_text(duplicate, self.table),
            codes[0].to_bytes(2, "big"),
        )

    def test_encode_accepts_explicit_chinese_code_override(self):
        encoded = encode_text("中", self.table, overrides={"中": 0x8140})
        self.assertEqual(encoded, b"\x81\x40")

    def test_encode_override_takes_priority_over_ascii_control_tag_bytes(self):
        encoded = encode_text(
            "12345",
            self.table,
            overrides={
                "1": 0x8140,
                "2": 0x8141,
                "3": 0x8142,
                "4": 0x8143,
                "5": 0x8144,
            },
        )
        self.assertEqual(
            encoded,
            b"\x81\x40\x81\x41\x81\x42\x81\x43\x81\x44",
        )

    def test_runtime_name_tokens_bypass_ascii_glyph_overrides(self):
        encoded = encode_text(
            "$n与$F",
            self.table,
            overrides={
                "$": 0x8140,
                "n": 0x8141,
                "F": 0x8142,
            },
        )
        self.assertEqual(
            encoded,
            b"$n" + self.table.inverse_characters["与"].to_bytes(2, "big") + b"$F",
        )

    def test_runtime_format_tokens_bypass_ascii_glyph_overrides(self):
        encoded = encode_text(
            "%s：%2$s",
            self.table,
            overrides={
                "%": 0x8140,
                "s": 0x8141,
                "2": 0x8142,
                "$": 0x8143,
            },
        )
        self.assertEqual(
            encoded,
            b"%s" + self.table.inverse_characters["："].to_bytes(2, "big") + b"%2$s",
        )

    def test_augmented_table_reads_explicit_override(self):
        augmented = augment_text_table(self.table, {"测": 0x987E})
        self.assertEqual(decode_text(b"\x98\x7e\x00", 0, augmented).text, "测")

    def test_augmented_table_rejects_code_collision(self):
        with self.assertRaises(SrwzTextEncodeError):
            augment_text_table(self.table, {"错": 0x8140})

    def test_encode_rejects_unmapped_character(self):
        with self.assertRaises(SrwzTextEncodeError) as raised:
            encode_text("🙂", self.table)
        self.assertEqual(raised.exception.character_index, 0)


if __name__ == "__main__":
    unittest.main()
