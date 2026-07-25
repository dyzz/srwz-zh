import random
import unittest

from tools.srwz.codec import (
    ByteReader,
    decode,
    encode,
    encode_coded_integer,
    flags_for_size,
    read_coded_integer,
)
from tools.srwz.codec_contract import SrwzCodecError


def coded_integer(value):
    if value < 0:
        raise ValueError("fixture values must be non-negative")
    groups = [value & 0x7F]
    value >>= 7
    while value:
        groups.append(value & 0x7F)
        value >>= 7
    groups.reverse()
    return bytes(
        (group << 1) | (1 if index == len(groups) - 1 else 0)
        for index, group in enumerate(groups)
    )


def stream(declared_size, body, *, flags=1, unknown_header_value=0):
    return (
        coded_integer(declared_size)
        + coded_integer(flags)
        + coded_integer(unknown_header_value)
        + body
    )


class CodedIntegerTests(unittest.TestCase):
    def test_reads_single_byte_value(self):
        reader = ByteReader(b"\x55")
        value = read_coded_integer(reader)
        self.assertEqual(value.value, 42)
        self.assertEqual((value.start, value.end, value.size), (0, 1, 1))

    def test_reads_multiple_bytes(self):
        reader = ByteReader(b"\x02\x01")
        value = read_coded_integer(reader)
        self.assertEqual(value.value, 128)
        self.assertEqual((value.start, value.end), (0, 2))

    def test_continues_from_initial_value(self):
        reader = ByteReader(b"\x11")
        value = read_coded_integer(reader, initial_value=3)
        self.assertEqual(value.value, 392)

    def test_reports_truncated_value_offset(self):
        reader = ByteReader(b"\x02")
        with self.assertRaises(SrwzCodecError) as raised:
            read_coded_integer(reader)
        self.assertEqual(raised.exception.offset, 1)
        self.assertIn("truncated coded integer", str(raised.exception))

    def test_rejects_value_over_byte_limit(self):
        reader = ByteReader(b"\x00\x00\x01")
        with self.assertRaises(SrwzCodecError) as raised:
            read_coded_integer(reader, max_bytes=2)
        self.assertEqual(raised.exception.offset, 2)
        self.assertIn("exceeds 2-byte limit", str(raised.exception))

    def test_encoder_round_trips_boundary_values(self):
        for expected in (0, 1, 63, 127, 128, 16383, 16384, 2**32):
            with self.subTest(expected=expected):
                value = read_coded_integer(
                    ByteReader(encode_coded_integer(expected))
                )
                self.assertEqual(value.value, expected)


class DecodeTests(unittest.TestCase):
    def test_literal_only_stream(self):
        # A zero match nibble is followed by an explicit zero coded integer.
        compressed = stream(3, b"\x03\x01abc")
        result = decode(compressed)
        self.assertEqual(result.output, b"abc")
        self.assertEqual(result.declared_size, 3)
        self.assertEqual(result.flags, 1)
        self.assertEqual(result.metadata["window_size"], 256)
        self.assertEqual(result.metadata["header_unknown_1"], 0)

    def test_regular_back_reference(self):
        compressed = stream(6, b"\x13abc\x25")
        self.assertEqual(decode(compressed).output, b"abcabc")

    def test_overlap_copy(self):
        compressed = stream(6, b"\x11a\x41")
        self.assertEqual(decode(compressed).output, b"aaaaaa")

    def test_extended_distance_and_length(self):
        compressed = stream(21, b"\x19abcdefghi\x00\x11\x17")
        self.assertEqual(
            decode(compressed).output,
            b"abcdefghiabcdefghiabc",
        )

    def test_preserves_conditional_unknown_header_value(self):
        compressed = (
            coded_integer(1)
            + coded_integer(0x61)
            + coded_integer(7)
            + coded_integer(0)
            + b"\x01\x01x"
        )
        result = decode(compressed)
        self.assertEqual(result.output, b"x")
        self.assertEqual(result.header_size, 4)
        self.assertEqual(result.metadata["header_unknown_0"], 7)
        self.assertEqual(result.metadata["header_unknown_1"], 0)

    def test_rejects_back_reference_before_output_start(self):
        compressed = stream(3, b"\x11a\x15")
        with self.assertRaises(SrwzCodecError) as raised:
            decode(compressed)
        self.assertEqual(raised.exception.offset, 5)
        self.assertIn("exceeds produced output size", str(raised.exception))

    def test_rejects_output_overrun(self):
        compressed = stream(4, b"\x11a\x31")
        with self.assertRaises(SrwzCodecError) as raised:
            decode(compressed)
        self.assertEqual(raised.exception.offset, 5)
        self.assertIn("exceeds remaining output size", str(raised.exception))

    def test_rejects_literal_output_overrun(self):
        compressed = stream(2, b"\x03\x01abc")
        with self.assertRaises(SrwzCodecError) as raised:
            decode(compressed)
        self.assertEqual(raised.exception.offset, 3)
        self.assertIn("literal run", str(raised.exception))

    def test_reports_truncated_literal_offset(self):
        compressed = stream(3, b"\x03\x01ab")
        with self.assertRaises(SrwzCodecError) as raised:
            decode(compressed)
        self.assertEqual(raised.exception.offset, 5)
        self.assertIn("truncated literal run", str(raised.exception))

    def test_rejects_declared_size_mismatch(self):
        compressed = stream(7, b"\x13abc\x25")
        with self.assertRaises(SrwzCodecError) as raised:
            decode(compressed)
        self.assertEqual(raised.exception.offset, len(compressed))
        self.assertIn("declared output size mismatch", str(raised.exception))

    def test_rejects_zero_literal_count_used_by_incompatible_encoder(self):
        compressed = stream(2, b"\x10\x01\x11")
        with self.assertRaises(SrwzCodecError) as raised:
            decode(compressed)
        self.assertEqual(raised.exception.offset, 3)
        self.assertIn("zero literal count", str(raised.exception))

    def test_rejects_zero_match_count_before_output_end(self):
        compressed = stream(2, b"\x01\x01a")
        with self.assertRaises(SrwzCodecError) as raised:
            decode(compressed)
        self.assertEqual(raised.exception.offset, 3)
        self.assertIn("zero match count", str(raised.exception))

    def test_consumed_excludes_trailing_padding(self):
        compressed = stream(3, b"\x03\x01abc")
        result = decode(compressed + b"\x00" * 16)
        self.assertEqual(result.consumed, len(compressed))
        self.assertEqual(len(compressed) + 16 - result.consumed, 16)

    def test_enforces_output_size_limit(self):
        compressed = stream(3, b"\x03\x01abc")
        with self.assertRaises(SrwzCodecError) as raised:
            decode(compressed, max_output_size=2)
        self.assertEqual(raised.exception.offset, 0)
        self.assertIn("exceeds limit", str(raised.exception))

    def test_enforces_structural_token_limit(self):
        compressed = stream(6, b"\x13abc\x25")
        with self.assertRaises(SrwzCodecError) as raised:
            decode(compressed, max_tokens=1)
        self.assertEqual(raised.exception.offset, 7)
        self.assertIn("token count", str(raised.exception))


class EncodeTests(unittest.TestCase):
    def test_flags_follow_observed_power_of_two_windows(self):
        self.assertEqual(flags_for_size(0), 1)
        self.assertEqual(flags_for_size(256), 1)
        self.assertEqual(flags_for_size(257), 3)
        self.assertEqual(flags_for_size(512), 3)
        self.assertEqual(flags_for_size(513), 5)
        self.assertEqual(flags_for_size(1_290_240), 27)

    def test_literal_strategy_round_trips(self):
        for source in (b"", b"x", b"literal data", bytes(range(256))):
            with self.subTest(size=len(source)):
                encoded = encode(source, strategy="literal")
                result = decode(encoded)
                self.assertEqual(result.output, source)
                self.assertEqual(result.consumed, len(encoded))

    def test_greedy_strategy_emits_useful_overlap_match(self):
        source = b"A" * 4096
        encoded = encode(source, strategy="greedy")
        self.assertEqual(decode(encoded).output, source)
        self.assertLess(len(encoded), 32)

    def test_greedy_groups_consecutive_matches_after_leading_literal(self):
        source = b"abcdefghXijklmnopYabcdefghijklmnop"
        events = []
        encoded = encode(source, strategy="greedy")
        self.assertEqual(
            decode(encoded, trace_sink=events.append).output,
            source,
        )
        blocks = [event for event in events if event["kind"] == "block"]
        self.assertTrue(blocks)
        self.assertTrue(
            all(block["literal_count"] > 0 for block in blocks)
        )
        self.assertTrue(
            any(block["match_count"] > 1 for block in blocks)
        )

    def test_greedy_strategy_is_deterministic(self):
        source = (b"SRWZ clean-room codec " * 100) + bytes(range(64))
        first = encode(source, strategy="greedy")
        second = encode(source, strategy="greedy")
        self.assertEqual(first, second)
        self.assertEqual(decode(first).output, source)

    def test_greedy_round_trips_seeded_random_inputs(self):
        random_source = random.Random(0x5352575A)
        for size in (2, 3, 31, 256, 1025):
            source = bytes(random_source.randrange(32) for _ in range(size))
            with self.subTest(size=size):
                self.assertEqual(
                    decode(encode(source, strategy="greedy")).output,
                    source,
                )

    def test_custom_conditional_header_round_trips(self):
        encoded = encode(
            b"x",
            strategy="literal",
            flags=0x61,
            header_unknown_0=7,
            header_unknown_1=3,
        )
        result = decode(encoded)
        self.assertEqual(result.output, b"x")
        self.assertEqual(result.metadata["header_unknown_0"], 7)
        self.assertEqual(result.metadata["header_unknown_1"], 3)

    def test_rejects_missing_conditional_header_value(self):
        with self.assertRaisesRegex(ValueError, "require header_unknown_0"):
            encode(b"x", flags=0x61)

    def test_rejects_unknown_strategy(self):
        with self.assertRaisesRegex(ValueError, "unknown encoding strategy"):
            encode(b"x", strategy="optimal")


if __name__ == "__main__":
    unittest.main()
