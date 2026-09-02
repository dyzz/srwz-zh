from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools.srwz.dialogue_speaker_colors import (
    DialogueSpeakerColorError,
    apply_dialogue_speaker_quote_constant,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DialogueSpeakerColorTest(unittest.TestCase):
    def setUp(self) -> None:
        config = json.loads(
            (PROJECT_ROOT / "config/full-story-components.json").read_text(
                encoding="utf-8"
            )
        )
        self.contract = config["dialogue_speaker_colors"]
        file_offset = int(self.contract["file_offset"], 0)
        original = bytes.fromhex(self.contract["original_block_hex"])
        executable = bytearray(file_offset + len(original) + 16)
        executable[file_offset : file_offset + len(original)] = original
        self.executable = bytes(executable)

    def test_quote_constant_restores_shared_speaker_color_recognizer(self) -> None:
        output, report = apply_dialogue_speaker_quote_constant(
            self.executable, self.contract
        )
        changed_offsets = [
            offset
            for offset, (before, after) in enumerate(
                zip(self.executable, output)
            )
            if before != after
        ]
        self.assertEqual(changed_offsets, [0x33E258, 0x33E259])
        self.assertEqual(report["changed_byte_count"], 2)
        self.assertEqual(report["source_quote"], "「")
        self.assertEqual(report["output_quote"], "“")
        self.assertEqual(report["preserved_parenthetical_quote"], "（")
        self.assertTrue(report["parenthetical_quote_preserved_byte_exact"])
        self.assertTrue(
            report["ordinary_dialogue_and_back_log_share_recognizer"]
        )
        self.assertTrue(report["replacement_reread_exact"])
        self.assertTrue(report["executable_size_preserved"])

        reread, reread_report = apply_dialogue_speaker_quote_constant(
            output, self.contract
        )
        self.assertEqual(reread, output)
        self.assertEqual(reread_report["changed_byte_count"], 0)
        self.assertTrue(reread_report["already_patched"])

    def test_quote_constant_preimage_drift_is_rejected(self) -> None:
        damaged = bytearray(self.executable)
        damaged[0x33E260] ^= 1
        with self.assertRaises(DialogueSpeakerColorError):
            apply_dialogue_speaker_quote_constant(
                bytes(damaged), self.contract
            )

    def test_active_chinese_story_corpus_no_longer_uses_japanese_quote(self) -> None:
        translations: list[str] = []
        for path in sorted(
            (PROJECT_ROOT / "corpus/zh/story-dialogue").glob("*.json")
        ):
            document = json.loads(path.read_text(encoding="utf-8"))
            translations.extend(
                entry["translation"] for entry in document["entries"]
            )
        self.assertEqual(len(translations), 83_668)
        self.assertEqual(sum("「" in text for text in translations), 0)
        self.assertGreater(sum(text.startswith("“") for text in translations), 0)
        self.assertGreater(sum(text.startswith("（") for text in translations), 0)


if __name__ == "__main__":
    unittest.main()
