import json
import unittest
from collections import Counter
from pathlib import Path

from tools.srwz.text import (
    PreparedTextEncoder,
    SrwzTextEncodeError,
    SrwzTextError,
    augment_text_table,
    control_notation_tokens,
    decode_text,
    encode_text,
    load_text_table,
    normalize_original_fullwidth_ascii,
    normalize_two_byte_visible_spaces,
    original_fullwidth_ascii_overrides,
    two_byte_visible_spaces,
    unrecognized_control_notation_offsets,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_ROOT = PROJECT_ROOT / "vendor" / "upstream-python"
TEXT_TABLE = UPSTREAM_ROOT / "project" / "tbl_all.json"
TAG_FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "control-tags.json"


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

    def test_control_notation_is_classified_without_splitting_tokens(self):
        tokens = control_notation_tokens(
            "第%2$s话%<width:64>$c$n<0><9>{7F}@<color:31>"
        )
        self.assertEqual(
            [(token.kind, token.text) for token in tokens],
            [
                ("runtime_format", "%2$s"),
                ("runtime_format", "%<width:64>"),
                ("runtime_substitution", "$c"),
                ("runtime_substitution", "$n"),
                ("runtime_substitution", "<0>"),
                ("runtime_substitution", "<9>"),
                ("raw_byte", "{7F}"),
                ("text_tag", "@<color:31>"),
            ],
        )

    def test_unknown_placeholder_like_syntax_is_fail_closed(self):
        text = "30%正常，%Q异常，$q异常，@<color:ZZ>异常"
        self.assertEqual(
            unrecognized_control_notation_offsets(text),
            (text.index("%Q"), text.index("$q"), text.index("@<")),
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

    def test_prepared_encoder_matches_one_shot_encoder(self):
        overrides = {"中": 0x8140, "文": 0x8141}
        encoder = PreparedTextEncoder(self.table, overrides)
        self.assertEqual(
            encoder.encode("中文", terminate=True),
            encode_text(
                "中文",
                self.table,
                overrides=overrides,
                terminate=True,
            ),
        )

    def test_prepared_encoder_validates_overrides_once(self):
        with self.assertRaisesRegex(ValueError, "one character"):
            PreparedTextEncoder(self.table, {"中文": 0x8140})
        with self.assertRaisesRegex(ValueError, "outside two bytes"):
            PreparedTextEncoder(self.table, {"中": 0x10000})

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

    def test_same_code_ascii_raster_override_stays_one_byte(self):
        encoded = encode_text(
            "9Jab",
            self.table,
            overrides={"9": 0x39, "J": 0x4A, "a": 0x61, "b": 0x62},
        )
        self.assertEqual(encoded, b"9Jab")

    def test_visible_ascii_uses_original_two_byte_glyph_codes(self):
        overrides = original_fullwidth_ascii_overrides(self.table)
        encoded = encode_text(
            "ZAFTPLANTLSWM29", self.table, overrides=overrides
        )
        self.assertEqual(
            encoded,
            bytes.fromhex(
                "8279826082658273"
                "826f826b8260826d8273"
                "826b82728276826c"
                "82518258"
            ),
        )
        self.assertEqual(len(overrides), 62)
        self.assertTrue(all(code >= 0x8000 for code in overrides.values()))

    def test_fullwidth_alphanumerics_normalize_to_ascii_identity(self):
        self.assertEqual(
            normalize_original_fullwidth_ascii("第１２话・ＺＡＦＴ"),
            "第12话・ZAFT",
        )

    def test_visible_spaces_use_stock_two_byte_glyph_at_storage_boundary(self):
        logical = "Anti Earth Union\nGovernment"
        stored = two_byte_visible_spaces(logical)
        self.assertEqual(stored, "Anti\u3000Earth\u3000Union\nGovernment")
        self.assertEqual(normalize_two_byte_visible_spaces(stored), logical)
        encoded = encode_text(
            stored,
            self.table,
            overrides=original_fullwidth_ascii_overrides(self.table),
        )
        self.assertNotIn(b"\x20", encoded)
        self.assertEqual(encoded.count(b"\x81\x40"), 2)

    def test_runtime_tokens_bypass_original_ascii_overrides(self):
        overrides = original_fullwidth_ascii_overrides(self.table)
        encoded = encode_text("%s与$F", self.table, overrides=overrides)
        self.assertEqual(encoded[:2], b"%s")
        self.assertEqual(encoded[-2:], b"$F")

    def test_runtime_substitution_tokens_bypass_ascii_glyph_overrides(self):
        encoded = encode_text(
            "$c与$f与$l与$n与$F",
            self.table,
            overrides={
                "$": 0x8140,
                "c": 0x8141,
                "f": 0x8142,
                "l": 0x8143,
                "n": 0x8141,
                "F": 0x8142,
            },
        )
        self.assertEqual(
            encoded,
            b"$c"
            + self.table.inverse_characters["与"].to_bytes(2, "big")
            + b"$f"
            + self.table.inverse_characters["与"].to_bytes(2, "big")
            + b"$l"
            + self.table.inverse_characters["与"].to_bytes(2, "big")
            + b"$n"
            + self.table.inverse_characters["与"].to_bytes(2, "big")
            + b"$F",
        )

    def test_runtime_format_tokens_bypass_ascii_glyph_overrides(self):
        encoded = encode_text(
            "%s：%2$s：%2d：%02d",
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
            b"%s"
            + self.table.inverse_characters["："].to_bytes(2, "big")
            + b"%2$s"
            + self.table.inverse_characters["："].to_bytes(2, "big")
            + b"%2d"
            + self.table.inverse_characters["："].to_bytes(2, "big")
            + b"%02d",
        )

    def test_lossless_runtime_format_tag_bypasses_ascii_glyph_overrides(self):
        encoded = encode_text(
            "%<width:64>",
            self.table,
            overrides={"%": 0x9865, "2": 0x8140, "d": 0x8141},
            terminate=True,
        )
        self.assertEqual(encoded, b"%2d\x00")

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
