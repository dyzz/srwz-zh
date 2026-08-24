from __future__ import annotations

import unittest
from unittest.mock import patch

from tools.srwz.codec_contract import DecodeResult
from tools.srwz.compressed_workspace import CompressedStreamWorkspace


def _decoded(output: bytes, *, consumed: int = 4) -> DecodeResult:
    return DecodeResult(
        output=output,
        consumed=consumed,
        declared_size=len(output),
        flags=1,
        header_size=1,
    )


class CompressedStreamWorkspaceTest(unittest.TestCase):
    def test_batches_writes_and_allows_only_one_final_compression(self) -> None:
        source = _decoded(b"abcd")
        reread = _decoded(b"wxyz")
        with (
            patch(
                "tools.srwz.compressed_workspace.decode_production",
                side_effect=[source, reread],
            ) as decoder,
            patch(
                "tools.srwz.compressed_workspace.reencode_changed_suffix",
                return_value=b"done",
            ) as encoder,
        ):
            workspace = CompressedStreamWorkspace.open("member chunk", b"base")
            workspace.replace(b"abcz", stage="first domain")
            workspace.replace(b"wxyz", stage="second domain")
            rebuilt, report = workspace.finalize(
                strategy="rust-fit",
                min_match_length=2,
                max_match_chain=16,
                lazy_matching=False,
                max_output_size=8,
            )

        self.assertEqual(rebuilt, b"done")
        self.assertEqual(decoder.call_count, 2)
        self.assertEqual(encoder.call_count, 1)
        self.assertEqual(report["initial_decode_count"], 1)
        self.assertEqual(report["write_stage_count"], 2)
        self.assertEqual(report["compression_count"], 1)
        self.assertEqual(
            [stage["stage"] for stage in report["stages"]],
            ["first domain", "second domain"],
        )

        with self.assertRaisesRegex(ValueError, "already compressed"):
            workspace.finalize(
                strategy="rust-fit",
                min_match_length=2,
                max_match_chain=16,
                lazy_matching=False,
                max_output_size=8,
            )
        with self.assertRaisesRegex(ValueError, "already finalized"):
            workspace.replace(b"wxyz", stage="late write")


if __name__ == "__main__":
    unittest.main()
