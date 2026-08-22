import json
import unittest
from pathlib import Path

from tools.build_story_component import (
    _discover_story_tickers,
    _load_overrides,
    _load_story_tickers,
    _write_story_tickers,
)
from tools.srwz.codec import decode_production as decode
from tools.srwz.iso_layout import (
    ExecutableOffsetSpec,
    read_executable_archive_offsets,
)
from tools.srwz.text import (
    decode_text,
    load_text_table,
    original_fullwidth_ascii_overrides,
    project_runtime_text_table,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class StoryTickerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(
            (PROJECT_ROOT / "config/story-component.json").read_text(
                encoding="utf-8"
            )
        )
        cls.table = load_text_table(
            PROJECT_ROOT / cls.config["source"]["text_table"]["path"]
        )
        cls.overrides, _proposal = _load_overrides(
            PROJECT_ROOT / cls.config["font"]["proposal"],
            PROJECT_ROOT / cls.config["font"]["allocation_registry"],
            PROJECT_ROOT / cls.config["source"]["base_codebook"]["path"],
        )
        cls.overrides.update(original_fullwidth_ascii_overrides(cls.table))
        reference = cls.config["translations"]["tickers"]
        _path, entries_by_source = _load_story_tickers(reference)

        cls.stage = (
            PROJECT_ROOT / cls.config["source"]["stage"]["path"]
        ).read_bytes()
        hb = (
            PROJECT_ROOT
            / "work/build/full-story-stage/components/HEDBDY/HB.BIN"
        ).read_bytes()
        cls.offsets = read_executable_archive_offsets(
            hb,
            ExecutableOffsetSpec(
                name="test STAGE offsets",
                member="HEDBDY/HB.BIN",
                table_start=30320,
                table_end=31144,
            ),
            len(cls.stage),
        )
        cls.source_chunks = [
            cls.stage[cls.offsets[index] : cls.offsets[index + 1]]
            for index in range(len(cls.offsets) - 1)
        ]
        cls.targets_by_stage, cls.inventory = _discover_story_tickers(
            cls.source_chunks,
            cls.table,
            entries_by_source,
            reference,
        )

    def test_structural_inventory_covers_every_registered_ticker(self):
        self.assertEqual(self.inventory["entry_count"], 46)
        self.assertEqual(self.inventory["target_count"], 89)
        self.assertEqual(self.inventory["stage_count"], 89)
        self.assertEqual(
            self.inventory["inventory_sha256"],
            "57a55b76a189dce8ec0479a0b03656c1155d7e8acb1dfc14cd62bcf45a4d4872",
        )
        self.assertTrue(self.inventory["structural_slots_exact"])
        self.assertEqual(
            sum(len(targets) for targets in self.targets_by_stage.values()),
            89,
        )

    def test_every_fixed_slot_writes_bounded_chinese_text(self):
        runtime_table = project_runtime_text_table(
            self.table, self.overrides
        )
        for stage_index, targets in sorted(self.targets_by_stage.items()):
            with self.subTest(stage=stage_index):
                decoded = decode(self.source_chunks[stage_index]).output
                rebuilt, report = _write_story_tickers(
                    decoded,
                    self.table,
                    stage_index=stage_index,
                    targets=targets,
                    overrides=self.overrides,
                )
                self.assertEqual(report["story_ticker_count"], 1)
                self.assertTrue(report["story_ticker_fixed_slots_exact"])
                target = targets[0]
                offset = target["decoded_offset"]
                slot_end = offset + target["source_slot_size"]
                self.assertEqual(decoded[:offset], rebuilt[:offset])
                self.assertEqual(decoded[slot_end:], rebuilt[slot_end:])
                reread = decode_text(
                    rebuilt,
                    offset,
                    runtime_table,
                    end=slot_end,
                )
                self.assertEqual(reread.text, target["translation"])

    def test_ticker_only_stages_are_not_lost(self):
        dialogue_stages = {
            int(path.stem.split("-")[1])
            for path in (PROJECT_ROOT / "corpus/zh/story-dialogue").glob(
                "stage-*.json"
            )
        }
        self.assertEqual(
            sorted(set(self.targets_by_stage) - dialogue_stages),
            [158, 159, 161, 162, 165, 166, 167, 168, 171, 172, 173, 174],
        )

    def test_issue_020_siberian_market_has_one_structural_runtime_slot(self):
        matches = [
            (stage_index, target)
            for stage_index, targets in self.targets_by_stage.items()
            for target in targets
            if target["source_text"]
            == "シベ鉄の大マーケット。旅の皆様にお値打ち品を大放出。"
        ]
        self.assertEqual(len(matches), 1)
        stage_index, target = matches[0]
        self.assertEqual(stage_index, 39)
        self.assertEqual(target["decoded_offset"], 0x3B64)
        self.assertEqual(target["source_slot_size"], 53)
        self.assertEqual(
            target["translation"],
            "西伯铁大市场，为旅客大放送超值商品。",
        )


if __name__ == "__main__":
    unittest.main()
