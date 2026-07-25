import struct
import unittest

from tools.verify_pcsx2_font_runtime import (
    PINE_READ32,
    PINE_READ64,
    PineError,
    parse_ok_response,
    read32_payload,
    read64_payload,
    request_frame,
)


class PineRuntimeProtocolTests(unittest.TestCase):
    def test_request_frame_includes_little_endian_total_size(self):
        self.assertEqual(
            request_frame(b"\x0f"),
            struct.pack("<I", 5) + b"\x0f",
        )

    def test_read64_payload_uses_consecutive_qword_addresses(self):
        self.assertEqual(
            read64_payload(0x1000, 16),
            (
                bytes([PINE_READ64])
                + struct.pack("<I", 0x1000)
                + bytes([PINE_READ64])
                + struct.pack("<I", 0x1008)
            ),
        )

    def test_read64_payload_rejects_partial_qword(self):
        with self.assertRaisesRegex(ValueError, "multiple of 8"):
            read64_payload(0x1000, 7)

    def test_read32_payload_uses_consecutive_word_addresses(self):
        self.assertEqual(
            read32_payload(0x2000, 8),
            (
                bytes([PINE_READ32])
                + struct.pack("<I", 0x2000)
                + bytes([PINE_READ32])
                + struct.pack("<I", 0x2004)
            ),
        )

    def test_read32_payload_rejects_partial_word(self):
        with self.assertRaisesRegex(ValueError, "multiple of 4"):
            read32_payload(0x2000, 3)

    def test_parse_ok_response_returns_only_command_values(self):
        packet = struct.pack("<I", 9) + b"\x00" + b"\x78\x56\x34\x12"
        self.assertEqual(
            parse_ok_response(packet),
            b"\x78\x56\x34\x12",
        )

    def test_parse_ok_response_rejects_failure(self):
        with self.assertRaisesRegex(PineError, "failed"):
            parse_ok_response(struct.pack("<I", 5) + b"\xff")


if __name__ == "__main__":
    unittest.main()
