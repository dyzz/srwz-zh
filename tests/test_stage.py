import struct
import unittest
from pathlib import Path

from tools.srwz.stage import parse_stage, read_stage_function_addresses
from tools.srwz.text import load_text_table


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEXT_TABLE = (
    PROJECT_ROOT / "vendor" / "upstream-python" / "project" / "tbl_all.json"
)


class StageParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.table = load_text_table(TEXT_TABLE)

    def test_parses_speaker_and_dialogue_section(self):
        data = bytearray(0x300)

        # Two valid references; the format skips the first non-dialogue block.
        struct.pack_into("<h", data, 0x90, 0)
        struct.pack_into("<h", data, 0x98, 0x100)
        struct.pack_into("<h", data, 0xA0, 0)
        struct.pack_into("<h", data, 0xA8, 0x120)

        struct.pack_into("<II", data, 0x120, 0x180, 1)
        struct.pack_into("<I", data, 0x180, 0x200)
        struct.pack_into("<I", data, 0x220, 0)
        struct.pack_into("<I", data, 0x230, 0x280)
        struct.pack_into("<I", data, 0x240, 0x60)
        data[0x280:0x28C] = b"Alice\nHello\x00"

        result = parse_stage(
            bytes(data),
            self.table,
            stage_index=1,
            base_address=0,
        )

        self.assertEqual(result.block_references, (0x100, 0x120))
        self.assertEqual(result.section_count, 1)
        self.assertEqual(result.speaker_count, 1)
        self.assertEqual(result.dialogue_count, 1)
        speaker, dialogue = result.entries
        self.assertEqual(
            (speaker.entry_id, dialogue.entry_id),
            (
                "story/001/speaker/001",
                "story/001/dialogue/01.01/0000",
            ),
        )
        self.assertEqual((speaker.kind, speaker.text, speaker.speaker_id), (
            "speaker",
            "Alice",
            1,
        ))
        self.assertEqual(
            (
                dialogue.kind,
                dialogue.section,
                dialogue.text,
                dialogue.pointer_offset,
                dialogue.text_offset,
                dialogue.speaker_id,
            ),
            ("dialogue", "Section 1.1", "Hello", 0x230, 0x280, 1),
        )

    def test_reads_observed_non_aligned_function_table_end(self):
        executable = bytearray(32)
        struct.pack_into("<III", executable, 4, 10, 20, 30)
        self.assertEqual(
            read_stage_function_addresses(bytes(executable), start=4, end=15),
            (10, 20, 30),
        )


if __name__ == "__main__":
    unittest.main()
