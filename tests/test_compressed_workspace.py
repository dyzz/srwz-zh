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


from tools.srwz import codec as _codec
from tools.srwz.compressed_workspace import CompressedArchiveWorkspace


class _ArchiveFixture:
    def setUp(self) -> None:
        self.chunks = [bytes(range(256)) * 8, b"stage text " * 300, b"\0" * 512 + b"tail" * 64]
        self.offsets = [0]
        stored = []
        for chunk in self.chunks:
            encoded = _codec.encode(chunk, strategy="greedy")
            allocation = encoded + bytes(64)
            stored.append(allocation)
            self.offsets.append(self.offsets[-1] + len(allocation))
        self.payload = b"".join(stored)

    def finalize(self, archive):
        return archive.finalize(strategy="rust-fit", min_match_length=3,
                                max_match_chain=64, lazy_matching=False)


@unittest.skipUnless(_codec._rust_compressor_path().is_file(), "build the Rust codec first")
class CompressedArchiveWorkspaceTest(_ArchiveFixture, unittest.TestCase):

    def test_chains_writers_and_compresses_each_changed_chunk_once(self) -> None:
        archive = CompressedArchiveWorkspace("STAGE", self.payload, self.offsets)
        first = bytearray(archive.view(1).output)
        first[0:5] = b"STAGE"
        archive.replace(1, first, stage="story")
        second = bytearray(archive.view(1).output)
        self.assertEqual(bytes(second[0:5]), b"STAGE")
        second[20:24] = b"name"
        archive.replace(1, second, stage="formation")
        archive.view(2)  # opened but unchanged
        with patch("tools.srwz.compressed_workspace.reencode_changed_suffix",
                   wraps=_codec.reencode_changed_suffix) as encoder:
            output, reports = self.finalize(archive)
        self.assertEqual(encoder.call_count, 1)
        self.assertEqual(sorted(reports), [1])
        self.assertEqual([row["stage"] for row in reports[1]["write_stages"]], ["story", "formation"])
        self.assertEqual(len(output), len(self.payload))
        start, end = self.offsets[0], self.offsets[1]
        self.assertEqual(output[start:end], self.payload[start:end])
        start, end = self.offsets[2], self.offsets[3]
        self.assertEqual(output[start:end], self.payload[start:end])
        start, end = self.offsets[1], self.offsets[2]
        self.assertEqual(_codec.decode_production(output[start:end]).output, bytes(second))

    def test_matches_chained_recompression_bytes(self) -> None:
        # One final compression equals compressing after every writer.
        archive = CompressedArchiveWorkspace("STAGE", self.payload, self.offsets)
        edits = [(0, b"AAAA"), (40, b"BBBB")]
        stored = self.payload[self.offsets[1]:self.offsets[2]]
        allocation = len(stored)
        for position, data in edits:
            decoded = _codec.decode_production(stored)
            changed = bytearray(decoded.output)
            changed[position:position + len(data)] = data
            stored = _codec.reencode_changed_suffix(
                stored[:decoded.consumed], bytes(changed), strategy="rust-fit",
                min_match_length=3, max_match_chain=64, max_output_size=allocation,
                original_result=decoded,
            )
            current = bytearray(archive.view(1).output)
            current[position:position + len(data)] = data
            archive.replace(1, current, stage=f"edit@{position}")
        output, reports = self.finalize(archive)
        start, end = self.offsets[1], self.offsets[2]
        self.assertEqual(output[start:start + len(stored)], stored)
        self.assertEqual(reports[1]["output_encoded_size"], len(stored))

    def test_codec_follows_the_last_writing_domain(self) -> None:
        archive = CompressedArchiveWorkspace("STAGE", self.payload, self.offsets)
        for index, stages in ((0, ["story"]), (1, ["story", "formation"])):
            for stage in stages:
                data = bytearray(archive.view(index).output)
                data[len(stage)] ^= 1
                archive.replace(index, data, stage=stage)
        seen = {}

        def codec_for(index, stages):
            seen[index] = stages
            return (2, 1024) if stages == ["story"] else (2, 16384)

        _output, reports = archive.finalize(strategy="rust-fit", min_match_length=3,
                                            max_match_chain=64, lazy_matching=False,
                                            codec_for=codec_for)
        self.assertEqual(seen, {0: ["story"], 1: ["story", "formation"]})
        self.assertEqual((reports[0]["min_match_length"], reports[0]["max_match_chain"]), (2, 1024))
        self.assertEqual((reports[1]["min_match_length"], reports[1]["max_match_chain"]), (2, 16384))

    def test_rejects_use_after_finalize_and_bad_offsets(self) -> None:
        archive = CompressedArchiveWorkspace("STAGE", self.payload, self.offsets)
        self.finalize(archive)
        with self.assertRaisesRegex(ValueError, "already finalized"):
            archive.view(0)
        with self.assertRaisesRegex(ValueError, "do not cover"):
            CompressedArchiveWorkspace("STAGE", self.payload, self.offsets[:-1])


@unittest.skipUnless(_codec._rust_compressor_path().is_file(), "build the Rust codec first")
class DecodedArchiveOverlayTest(_ArchiveFixture, unittest.TestCase):
    def test_overlay_hands_decoded_edits_to_another_owner(self) -> None:
        upstream = CompressedArchiveWorkspace("STAGE", self.payload, self.offsets)
        edited = bytearray(upstream.view(2).output)
        edited[-4:] = b"done"
        upstream.replace(2, edited, stage="story")
        overlay = upstream.export_overlay()

        downstream = CompressedArchiveWorkspace("STAGE", self.payload, self.offsets)
        header = downstream.import_overlay(overlay, stage="story component")
        self.assertEqual([row["index"] for row in header["chunks"]], [2])
        self.assertEqual(downstream.view(2).output, bytes(edited))
        later = bytearray(downstream.view(2).output)
        later[:4] = b"head"
        downstream.replace(2, later, stage="formation")
        _output, reports = self.finalize(downstream)
        self.assertEqual([row["stage"] for row in reports[2]["write_stages"]],
                         ["story component", "formation"])

    def test_overlay_rejects_other_sources_and_damage(self) -> None:
        upstream = CompressedArchiveWorkspace("STAGE", self.payload, self.offsets)
        edited = bytearray(upstream.view(0).output)
        edited[0] ^= 1
        upstream.replace(0, edited, stage="story")
        overlay = upstream.export_overlay()
        other = bytearray(self.payload)
        other[-1] ^= 1
        with self.assertRaisesRegex(ValueError, "another source"):
            CompressedArchiveWorkspace("STAGE", bytes(other), self.offsets).import_overlay(overlay, stage="x")
        damaged = overlay[:-1] + bytes([overlay[-1] ^ 1])
        with self.assertRaisesRegex(ValueError, "damaged"):
            CompressedArchiveWorkspace("STAGE", self.payload, self.offsets).import_overlay(damaged, stage="x")
