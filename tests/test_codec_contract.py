import unittest

from tools.srwz.codec_contract import CodedInteger, DecodeResult, SrwzCodecError


class CodecContractTests(unittest.TestCase):
    def test_coded_integer_span(self):
        value = CodedInteger(value=128, start=3, end=5)
        self.assertEqual(value.size, 2)

    def test_decode_result_requires_exact_declared_size(self):
        with self.assertRaisesRegex(ValueError, "declared_size"):
            DecodeResult(
                output=b"abc",
                consumed=4,
                declared_size=2,
                flags=0,
                header_size=1,
            )

    def test_codec_error_reports_hex_offset(self):
        error = SrwzCodecError("truncated coded integer", offset=31)
        self.assertIn("0x1F", str(error))


if __name__ == "__main__":
    unittest.main()
