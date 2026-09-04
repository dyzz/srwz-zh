from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from build_story_component import (  # noqa: E402
    _discover_z_reports,
    _load_overrides,
    _load_z_reports,
    _read_iso_member,
    _write_z_reports,
)
from srwz.codec import decode_production as decode  # noqa: E402
from srwz.iso_layout import (  # noqa: E402
    ExecutableOffsetSpec,
    read_executable_archive_offsets,
)
from srwz.text import load_text_table  # noqa: E402


class ZReportCoverageTest(unittest.TestCase):
    def test_structural_inventory_and_fixed_slots_cover_every_report(self) -> None:
        config_path = PROJECT_ROOT / "config/story-component.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        source = config["source"]
        translations = config["translations"]

        _corpus_path, entries = _load_z_reports(translations["z_reports"])
        source_stage = (PROJECT_ROOT / source["stage"]["path"]).read_bytes()
        source_hb = _read_iso_member(
            PROJECT_ROOT / source["iso"],
            source["hb"],
        )
        offsets = read_executable_archive_offsets(
            source_hb,
            ExecutableOffsetSpec(
                name="test Z Report STAGE offsets",
                member="HEDBDY/HB.BIN",
                table_start=30320,
                table_end=31144,
            ),
            len(source_stage),
        )
        source_chunks = [
            source_stage[offsets[index] : offsets[index + 1]]
            for index in range(len(offsets) - 1)
        ]
        decoded_chunks = [decode(chunk).output for chunk in source_chunks]
        table = load_text_table(PROJECT_ROOT / source["text_table"]["path"])

        by_stage, inventory = _discover_z_reports(
            decoded_chunks,
            table,
            entries,
            translations["z_reports"],
        )
        self.assertEqual(
            inventory,
            {
                "entry_count": 5,
                "target_count": 6,
                "stage_count": 5,
                "stage_indices": [33, 36, 66, 119, 127],
                "inventory_sha256": (
                    "79f18d4287371f061d39c1d320f9bd05"
                    "a3052c2fc462c281cb29ccae90d23d90"
                ),
                "structural_slots_exact": True,
            },
        )
        self.assertEqual(
            [
                (
                    stage_index,
                    target["record_offset"],
                    target["decoded_offset"],
                    target["source_slot_size"],
                    target["translation"],
                )
                for stage_index, targets in sorted(by_stage.items())
                for target in targets
            ],
            [
                (33, 0x2188, 0x5BA0, 47, "武装“米加火箭发射器”已追加"),
                (36, 0x54C8, 0xDD50, 23, "莎拉队获得PP+50"),
                (36, 0x54E8, 0xDD70, 27, "阿蒂特队获得PP+50"),
                (66, 0xB598, 0x1BF40, 39, "武装“大魔神推进器”已追加"),
                (119, 0xE238, 0x25A80, 29, "武装“G-Bit”已追加"),
                (127, 0x10588, 0x2B1D0, 29, "武装“G-Bit”已追加"),
            ],
        )

        overrides, _proposal = _load_overrides(
            PROJECT_ROOT / config["font"]["proposal"],
            PROJECT_ROOT / config["font"]["allocation_registry"],
            PROJECT_ROOT / source["base_codebook"]["path"],
        )
        reports = []
        for stage_index, targets in sorted(by_stage.items()):
            output, report = _write_z_reports(
                decoded_chunks[stage_index],
                table,
                stage_index=stage_index,
                targets=targets,
                overrides=overrides,
            )
            self.assertNotEqual(output, decoded_chunks[stage_index])
            reports.append(report)
        self.assertEqual(sum(item["z_report_count"] for item in reports), 6)
        self.assertTrue(all(item["z_report_fixed_slots_exact"] for item in reports))
        self.assertTrue(
            all(item["z_report_translated_reread_exact"] for item in reports)
        )


if __name__ == "__main__":
    unittest.main()
