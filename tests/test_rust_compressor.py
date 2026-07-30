import hashlib
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from tools.srwz import codec
from tools.srwz.codec import decode, encode, reencode_changed_suffix


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CRATE_ROOT = PROJECT_ROOT / "tools/native/srwz-codec-rs"
ORIGINAL_TITLE_VT1 = (
    PROJECT_ROOT / "work/build/ui-p0/components/DATA/VT1.BIN"
)
LOCALIZED_TITLE_VT1 = (
    PROJECT_ROOT / "work/build/title-menu-zh/components/DATA/VT1.BIN"
)
TITLE_CHUNK_START = 10_965_424
TITLE_CHUNK_SPAN = 468_320
TITLE_ENCODED_SHA256 = (
    "ebda9c0a290504ff87d60d1fbdbe356b1c408b27176875d94a7626103451f224"
)


def read_slice(path: Path, start: int, size: int) -> bytes:
    with path.open("rb") as handle:
        handle.seek(start)
        return handle.read(size)


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

    def test_changed_suffix_preserves_round_trip_contract(self):
        source = (b"abcdefgh" * 2048) + bytes(range(128))
        original = encode(source, strategy="greedy")
        modified = source[:4097] + b"ZH" + source[4099:]
        with self.rust_binary():
            encoded = reencode_changed_suffix(
                original,
                modified,
                strategy="rust-maximum",
                min_match_length=2,
            )
        result = decode(encoded)
        self.assertEqual(result.output, modified)
        self.assertEqual(result.consumed, len(encoded))

    def test_real_localized_title_chunk_fits_original_span(self):
        if not ORIGINAL_TITLE_VT1.is_file() or not LOCALIZED_TITLE_VT1.is_file():
            self.skipTest("ignored VT1 title fixtures are not available")
        original_stream = read_slice(
            ORIGINAL_TITLE_VT1,
            TITLE_CHUNK_START,
            TITLE_CHUNK_SPAN,
        )
        localized_stream = read_slice(
            LOCALIZED_TITLE_VT1,
            TITLE_CHUNK_START,
            TITLE_CHUNK_SPAN,
        )
        original = decode(original_stream)
        localized = decode(localized_stream)
        self.assertEqual(len(original.output), 2_349_392)
        self.assertEqual(len(localized.output), 2_349_392)
        self.assertEqual(
            sum(
                before != after
                for before, after in zip(original.output, localized.output)
            ),
            12_514,
        )
        with self.rust_binary():
            encoded = encode(
                localized.output,
                strategy="rust-maximum",
                flags=original.flags,
                min_match_length=3,
                max_output_size=TITLE_CHUNK_SPAN,
            )
        self.assertEqual(len(encoded), 463_318)
        self.assertEqual(
            hashlib.sha256(encoded).hexdigest(),
            TITLE_ENCODED_SHA256,
        )
        reread = decode(encoded)
        self.assertEqual(reread.output, localized.output)
        self.assertEqual(reread.consumed, len(encoded))


if __name__ == "__main__":
    unittest.main()
