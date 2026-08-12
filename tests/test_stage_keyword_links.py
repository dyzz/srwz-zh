import json
import unittest
from pathlib import Path

from tools.srwz.codec import decode_production as decode
from tools.srwz.iso9660 import SECTOR_SIZE, member_map, scan_iso9660
from tools.srwz.iso_layout import (
    ExecutableOffsetSpec,
    read_executable_archive_offsets,
)
from tools.srwz.stage import parse_stage, read_stage_function_addresses
from tools.srwz.text import load_text_table


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _balanced_keyword_span_count(text: str) -> int:
    depth = 0
    count = 0
    for character in text:
        if character == "《":
            depth += 1
            if depth != 1:
                raise AssertionError(f"nested keyword marker in {text!r}")
        elif character == "》":
            if depth != 1:
                raise AssertionError(f"unmatched keyword end in {text!r}")
            depth = 0
            count += 1
    if depth:
        raise AssertionError(f"unmatched keyword start in {text!r}")
    return count


def _keyword_spans(text: str) -> tuple[str, ...]:
    spans = []
    cursor = 0
    while True:
        start = text.find("《", cursor)
        if start < 0:
            return tuple(spans)
        end = text.find("》", start + 1)
        if end < 0:
            raise AssertionError(f"unmatched keyword start in {text!r}")
        if end == start + 1:
            raise AssertionError(f"empty keyword span in {text!r}")
        spans.append(text[start + 1 : end])
        cursor = end + 1


def _visible_book_quoted_keyword_indices(text: str) -> tuple[int, ...]:
    indices = []
    cursor = 0
    span_index = 0
    while True:
        start = text.find("《", cursor)
        if start < 0:
            return tuple(indices)
        end = text.find("》", start + 1)
        if end < 0:
            raise AssertionError(f"unmatched keyword start in {text!r}")
        if start > 0 and text[start - 1] == "『" and text[end + 1 : end + 2] == "』":
            indices.append(span_index)
        cursor = end + 1
        span_index += 1


class StageKeywordLinkTests(unittest.TestCase):
    def test_every_source_keyword_span_is_preserved_by_the_translation(self):
        config = json.loads(
            (PROJECT_ROOT / "config/story-component.json").read_text(
                encoding="utf-8"
            )
        )["source"]
        source_stage = (PROJECT_ROOT / config["stage"]["path"]).read_bytes()
        source_slps = (PROJECT_ROOT / config["slps"]["path"]).read_bytes()
        source_iso = PROJECT_ROOT / config["iso"]
        hb_member = member_map(scan_iso9660(source_iso))[config["hb"]["member"]]
        with source_iso.open("rb") as source:
            source.seek(hb_member.extent_lba * SECTOR_SIZE)
            source_hb = source.read(hb_member.size)

        offsets = read_executable_archive_offsets(
            source_hb,
            ExecutableOffsetSpec(
                name="HEDBDY/HB.BIN STAGE offsets",
                member=config["hb"]["member"],
                table_start=30320,
                table_end=31144,
            ),
            len(source_stage),
        )
        functions = read_stage_function_addresses(source_slps)
        table = load_text_table(PROJECT_ROOT / config["text_table"]["path"])

        keyword_entries = 0
        keyword_spans = 0
        mismatches = []
        visible_quote_mismatches = []
        visible_quote_span_count = 0
        stage001_term_pairs = set()
        for stage_index in range(len(offsets) - 1):
            corpus_path = (
                PROJECT_ROOT
                / f"corpus/zh/story-dialogue/stage-{stage_index:03d}.json"
            )
            if not corpus_path.exists():
                continue
            translations = {
                entry["id"]: entry["translation"]
                for entry in json.loads(
                    corpus_path.read_text(encoding="utf-8")
                )["entries"]
            }
            parsed = parse_stage(
                decode(
                    source_stage[
                        offsets[stage_index] : offsets[stage_index + 1]
                    ]
                ).output,
                table,
                stage_index=stage_index,
                function_address=functions[stage_index],
            )
            for source_entry in parsed.entries:
                if source_entry.kind != "dialogue":
                    continue
                source_count = _balanced_keyword_span_count(source_entry.text)
                if source_count == 0:
                    continue
                keyword_entries += 1
                keyword_spans += source_count
                translated_count = _balanced_keyword_span_count(
                    translations[source_entry.entry_id]
                )
                source_visible_quote_indices = _visible_book_quoted_keyword_indices(
                    source_entry.text
                )
                translated_visible_quote_indices = (
                    _visible_book_quoted_keyword_indices(
                        translations[source_entry.entry_id]
                    )
                )
                visible_quote_span_count += len(source_visible_quote_indices)
                if translated_visible_quote_indices != source_visible_quote_indices:
                    visible_quote_mismatches.append(
                        (
                            source_entry.entry_id,
                            source_visible_quote_indices,
                            translated_visible_quote_indices,
                        )
                    )
                if stage_index == 1:
                    stage001_term_pairs.update(
                        zip(
                            _keyword_spans(source_entry.text),
                            _keyword_spans(translations[source_entry.entry_id]),
                        )
                    )
                if translated_count != source_count:
                    mismatches.append(
                        (
                            source_entry.entry_id,
                            source_count,
                            translated_count,
                        )
                    )

        self.assertEqual(keyword_entries, 111)
        self.assertEqual(keyword_spans, 122)
        self.assertEqual(mismatches, [])
        self.assertEqual(visible_quote_span_count, 5)
        self.assertEqual(visible_quote_mismatches, [])
        self.assertEqual(
            stage001_term_pairs,
            {
                ("グローリー・スター", "荣耀之星"),
                ("ティターンズ", "提坦斯"),
                ("エゥーゴ", "奥古"),
            },
        )
        stage001 = json.loads(
            (PROJECT_ROOT / "corpus/zh/story-dialogue/stage-001.json").read_text(
                encoding="utf-8"
            )
        )
        translations = {
            entry["id"]: entry["translation"] for entry in stage001["entries"]
        }
        self.assertIn(
            "『《荣耀之星》』",
            translations["story/001/dialogue/02.01/0006"],
        )


if __name__ == "__main__":
    unittest.main()
