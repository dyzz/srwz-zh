import shutil
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from tools.srwz import codec
from tools.srwz.codec import (
    decode,
    decode_production,
    encode,
    reencode_changed_suffix,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CRATE_ROOT = PROJECT_ROOT / "tools/native/srwz-codec-rs"
class RustCompressorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cargo = shutil.which("cargo")
        if cargo is None:
            raise unittest.SkipTest("Cargo is not installed")
        subprocess.run(
            [
                "python3",
                "tools/build_rust_compressor.py",
                "--force",
            ],
            check=True,
            cwd=PROJECT_ROOT,
            capture_output=True,
        )
        cls.binary = (
            PROJECT_ROOT
            / "work/toolchain/srwz-compressor-rs"
            / "target/release/srwz-compress"
        )
        if not cls.binary.is_file():
            raise AssertionError("Cargo did not build srwz-compress")

    def rust_binary(self):
        return mock.patch.object(
            codec,
            "_rust_compressor_path",
            return_value=self.binary,
        )

    def test_stream_is_deterministic_and_python_decoder_compatible(self):
        source = (
            bytes(range(256))
            + (b"SRWZ clean-room Rust compressor " * 400)
            + (b"\0" * 4096)
        )
        with self.rust_binary():
            first = encode(
                source,
                strategy="rust-maximum",
                min_match_length=2,
            )
            second = encode(
                source,
                strategy="rust-maximum",
                min_match_length=2,
            )
        self.assertEqual(first, second)
        result = decode(first)
        self.assertEqual(result.output, source)
        self.assertEqual(result.consumed, len(first))

    def test_rust_decoder_matches_python_result_and_metadata(self):
        source = bytes(range(256)) + (b"SRWZ Rust decoder " * 700)
        with self.rust_binary():
            encoded = encode(source, strategy="rust-fit")
            rust = decode_production(encoded)
        python = decode(encoded)
        self.assertEqual(rust, python)

    def test_changed_suffix_preserves_round_trip_contract(self):
        source = (b"abcdefgh" * 2048) + bytes(range(128))
        with self.rust_binary():
            original = encode(source, strategy="rust-fit")
            modified = source[:4097] + b"ZH" + source[4099:]
            encoded = reencode_changed_suffix(
                original,
                modified,
                strategy="rust-maximum",
                min_match_length=2,
            )
            full = encode(
                modified,
                strategy="rust-maximum",
                flags=decode(original).flags,
                min_match_length=2,
            )
        self.assertEqual(encoded, full)
        result = decode(encoded)
        self.assertEqual(result.output, modified)
        self.assertEqual(result.consumed, len(encoded))

    def test_changed_suffix_reuses_a_locked_original_decode(self):
        source = (b"abcdefgh" * 2048) + bytes(range(128))
        with self.rust_binary():
            original = encode(source, strategy="rust-fit")
            original_result = decode(original)
            modified = source[:4097] + b"ZH" + source[4099:]
            reference = reencode_changed_suffix(
                original,
                modified,
                strategy="rust-fit",
                min_match_length=2,
            )
            reused = reencode_changed_suffix(
                original,
                modified,
                strategy="rust-fit",
                min_match_length=2,
                original_result=original_result,
            )
        self.assertEqual(reused, reference)

    def test_rust_reencode_never_calls_python_decoder(self):
        source = (b"one Rust decode path " * 800) + bytes(range(128))
        with self.rust_binary():
            original = encode(source, strategy="rust-fit")
            original_result = decode_production(original)
            modified = source[:2048] + b"ZH" + source[2050:]
            with mock.patch.object(
                codec,
                "decode",
                side_effect=AssertionError("Python decoder entered production path"),
            ):
                encoded = reencode_changed_suffix(
                    original,
                    modified,
                    strategy="rust-fit",
                    original_result=original_result,
                )
                reread = decode_production(encoded)
        self.assertEqual(reread.output, modified)


if __name__ == "__main__":
    unittest.main()
