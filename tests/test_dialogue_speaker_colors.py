from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools.srwz.dialogue_speaker_colors import (
    DialogueSpeakerColorError,
    apply_dialogue_speaker_quote_constant,
    apply_dialogue_speaker_prefixes,
    verify_dialogue_speaker_prefixes,
)
from tools.srwz.text import load_text_table, PreparedTextEncoder


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
        assignments = json.loads((PROJECT_ROOT / 'config/encoding/zh-release-font-assignments.json').read_text())
        overrides = {row['character']: int(row['code'], 16)
                     for key in ('primary_assignments', 'surface_alias_assignments')
                     for row in assignments[key]}
        table = load_text_table(PROJECT_ROOT / 'vendor/upstream-python/project/tbl_all.json')
        self.encoder = PreparedTextEncoder(table, overrides)
        self.prefixes = {text: self.encoder.encode(text, terminate=False) for text in ('“', '（')}

    def test_quote_constant_restores_shared_speaker_color_recognizer(self) -> None:
        output, report = apply_dialogue_speaker_quote_constant(
            self.executable, self.contract, encoded_prefixes=self.prefixes
        )
        changed_offsets = [
            offset
            for offset, (before, after) in enumerate(
                zip(self.executable, output)
            )
            if before != after
        ]
        self.assertEqual(changed_offsets, [0x33E258, 0x33E259, 0x33E260, 0x33E261])
        self.assertEqual(report["changed_byte_count"], 4)
        self.assertEqual(report["source_quote"], "「")
        self.assertEqual(report["output_quote"], "“")
        self.assertEqual(report["parenthetical_quote"], "（")
        self.assertTrue(report["prefixes_match_production_encoding"])
        self.assertTrue(
            report["ordinary_dialogue_and_back_log_share_recognizer"]
        )
        self.assertTrue(report["replacement_reread_exact"])
        self.assertTrue(report["executable_size_preserved"])

        reread, reread_report = apply_dialogue_speaker_quote_constant(
            output, self.contract, encoded_prefixes=self.prefixes
        )
        self.assertEqual(reread, output)
        self.assertEqual(reread_report["changed_byte_count"], 0)
        self.assertTrue(reread_report["already_patched"])

    def test_quote_constant_preimage_drift_is_rejected(self) -> None:
        damaged = bytearray(self.executable)
        damaged[0x33E260] ^= 1
        with self.assertRaises(DialogueSpeakerColorError):
            apply_dialogue_speaker_quote_constant(
                bytes(damaged), self.contract, encoded_prefixes=self.prefixes
            )

    def test_all_editions_migrate_old_partial_patch_and_preserve_other_bytes(self):
        for edition, offset in (('original', 0x33E258), ('best', 0x33EA48), ('sp', 0x3B0ED8)):
            with self.subTest(edition=edition):
                source = bytearray(b'\x5a' * (offset + 32))
                source[offset:offset+16] = bytes.fromhex('91410000000000008169000000000000')
                output, report = apply_dialogue_speaker_prefixes(bytes(source), edition, encoded_prefixes=self.prefixes)
                self.assertEqual(report['changed_offsets'], [f'0x{offset+8:X}', f'0x{offset+9:X}'])
                self.assertTrue(report['migrated_spoken_quote_only_patch'])
                self.assertEqual(output[:offset], source[:offset])
                self.assertEqual(output[offset+16:], source[offset+16:])
                again, second = apply_dialogue_speaker_prefixes(output, edition, encoded_prefixes=self.prefixes)
                self.assertEqual(again, output)
                self.assertTrue(second['already_patched'])
                self.assertEqual(second['changed_byte_count'], 0)

    def test_production_encoder_controls_both_dialogue_prefixes(self):
        output, _ = apply_dialogue_speaker_quote_constant(self.executable, self.contract, encoded_prefixes=self.prefixes)
        for text, offset in (('“', 0x33E258), ('（', 0x33E260)):
            self.assertEqual(output[offset:offset+2], self.encoder.encode(text, terminate=False))
        wrong = dict(self.prefixes, **{'（': bytes.fromhex('8169')})
        with self.assertRaisesRegex(DialogueSpeakerColorError, 'production encoding'):
            apply_dialogue_speaker_quote_constant(self.executable, self.contract, encoded_prefixes=wrong)

    def test_independent_readback_rejects_old_parenthesis_and_padding_drift(self):
        output, _ = apply_dialogue_speaker_quote_constant(self.executable, self.contract, encoded_prefixes=self.prefixes)
        for offset in (0x33E260, 0x33E262, 0x33E267):
            with self.subTest(offset=offset):
                damaged = bytearray(output)
                damaged[offset] ^= 1
                with self.assertRaises(DialogueSpeakerColorError):
                    verify_dialogue_speaker_prefixes(bytes(damaged), 'original', encoded_prefixes=self.prefixes)
                with self.assertRaises(DialogueSpeakerColorError):
                    apply_dialogue_speaker_prefixes(bytes(damaged), 'original', encoded_prefixes=self.prefixes)

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
