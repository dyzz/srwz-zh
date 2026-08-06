import struct
import tempfile
import unittest
from pathlib import Path

from tools.probe_srwz_battle_text import probe_srvc_battle_text
from tools.srwz.text import encode_text, load_text_table


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEXT_TABLE = (
    PROJECT_ROOT
    / "vendor"
    / "upstream-python"
    / "project"
    / "tbl_all.json"
)


class SrvcBattleTextProbeTests(unittest.TestCase):
    def test_locates_repeated_text_in_its_seg_chunk(self):
        table = load_text_table(TEXT_TABLE)
        line = "「一気に間合いをっ！」"
        encoded = encode_text(line, table, terminate=True)
        first_chunk = bytes(16)
        second_chunk = bytes(9) + encoded + bytes(7) + encoded + bytes(5)
        archive = first_chunk + second_chunk
        seg = struct.pack("<3I", 0, len(first_chunk), len(archive))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            seg_path = root / "SRVC.SEG"
            bin_path = root / "SRVC.BIN"
            seg_path.write_bytes(seg)
            bin_path.write_bytes(archive)

            report = probe_srvc_battle_text(
                seg_path=seg_path,
                bin_path=bin_path,
                text_table_path=TEXT_TABLE,
                needle="一気に間合いをっ！",
            )

        self.assertEqual(report["source"]["chunk_count"], 2)
        self.assertEqual(report["probe"]["occurrence_count"], 2)
        self.assertEqual(
            [item["chunk_index"] for item in report["probe"]["occurrences"]],
            [1, 1],
        )
        self.assertEqual(
            [item["context_text"] for item in report["probe"]["occurrences"]],
            [line, line],
        )
        self.assertTrue(
            report["checks"]["all_contexts_decode_without_unknown_codes"]
        )


if __name__ == "__main__":
    unittest.main()
