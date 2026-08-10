import struct
import unittest
from pathlib import Path

from tools.srwz.stage import (
    parse_stage,
    parse_stage_system_dialogues,
    read_stage_function_addresses,
)
from tools.srwz.text import load_text_table
from tools.srwz.writers import replace_stage_system_dialogues_in_place


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

    def test_parses_chunk_zero_system_dialogue_signature(self):
        data = bytearray(0x280)
        struct.pack_into("<I", data, 0x100, 0x200)
        struct.pack_into("<I", data, 0x110, 0x3A)
        data[0x200:0x20C] = b"Alice\nHello\x00"

        entries = parse_stage_system_dialogues(
            bytes(data),
            self.table,
            base_address=0,
        )

        self.assertEqual(len(entries), 1)
        self.assertEqual(
            entries[0].to_mapping(),
            {
                "id": "story/000/system-dialogue/000100",
                "ordinal": 0,
                "pointer_offset": 0x100,
                "text_offset": 0x200,
                "speaker": "Alice",
                "text": "Hello",
            },
        )

    def test_replaces_chunk_zero_system_dialogue_in_source_slot(self):
        data = bytearray(0x280)
        struct.pack_into("<I", data, 0x100, 0x200)
        struct.pack_into("<I", data, 0x110, 0x3A)
        data[0x200:0x220] = b"Alice\nHello\x00" + bytes(20)

        write = replace_stage_system_dialogues_in_place(
            bytes(data),
            self.table,
            replacements={
                "story/000/system-dialogue/000100": ("Bob", "Bye"),
            },
            base_address=0,
        )

        self.assertEqual(len(write.data), len(data))
        self.assertEqual(struct.unpack_from("<I", write.data, 0x100)[0], 0x200)
        self.assertEqual(write.mode, "fixed_source_allocations")
        reread = parse_stage_system_dialogues(
            write.data,
            self.table,
            base_address=0,
        )
        self.assertEqual((reread[0].speaker, reread[0].text), ("Bob", "Bye"))


if __name__ == "__main__":
    unittest.main()
