import unittest
from unittest import mock

from tools.srwz import codec
from tools.srwz.compressed_workspace import CompressedStreamWorkspace


class CompressedWorkspaceTests(unittest.TestCase):
    def test_all_writes_share_one_decode_and_one_final_compression(self):
        source = (b"workspace source " * 256) + bytes(range(64))
        stored = codec.encode(source, strategy="rust-fit")
        with mock.patch(
            "tools.srwz.compressed_workspace.decode_production",
            wraps=codec.decode_production,
        ) as decoder, mock.patch(
            "tools.srwz.compressed_workspace.reencode_changed_suffix",
            wraps=codec.reencode_changed_suffix,
        ) as compressor:
            workspace = CompressedStreamWorkspace.open("test", stored)
            first = bytearray(workspace.current)
            first[10:12] = b"ZH"
            workspace.replace(bytes(first), stage="first")
            second = bytearray(workspace.current)
            second[20:22] = b"CN"
            workspace.replace(bytes(second), stage="second")
            rebuilt, report = workspace.finalize(
                strategy="rust-fit",
                min_match_length=2,
                max_match_chain=1024,
                lazy_matching=False,
                max_output_size=len(stored) + 64,
            )
        self.assertEqual(decoder.call_count, 2)
        self.assertEqual(compressor.call_count, 1)
        self.assertEqual(codec.decode_production(rebuilt).output, bytes(second))
        self.assertEqual(report["initial_decode_count"], 1)
        self.assertEqual(report["write_stage_count"], 2)
        self.assertEqual(report["compression_count"], 1)
        self.assertEqual(report["final_readback_decode_count"], 1)


if __name__ == "__main__":
    unittest.main()
