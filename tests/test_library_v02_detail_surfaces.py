import hashlib
import json
import sys
import unittest
from pathlib import Path

from tools.srwz.codec import decode_production
from tools.srwz.library_menu import build_jtim_library_menu


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))
from build_library_v02_component import (
    CLOSING,
    OPENING,
    reflow_body,
)


class LibraryV02DetailSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.remaining = json.loads(
            (PROJECT_ROOT / "corpus/zh/menu/remaining-ui.json").read_text(
                encoding="utf-8"
            )
        )
        cls.work_titles = json.loads(
            (
                PROJECT_ROOT / "corpus/zh/auto-demo-work-titles.json"
            ).read_text(encoding="utf-8")
        )
        cls.library_scope = json.loads(
            (PROJECT_ROOT / "config/library/v0.2.0.json").read_text(
                encoding="utf-8"
            )
        )

    def test_detail_page_labels_are_selected_for_writeback(self):
        self.assertEqual(
            {
                offset: self.remaining["slps_by_offset"].get(offset)
                for offset in (
                    "0x33E050",
                    "0x33E068",
                    "0x33E078",
                    "0x33E088",
                    "0x33E0A0",
                    "0x33E0B8",
                    "0x33E0C8",
                    "0x33E0D0",
                    "0x33E0E8",
                    "0x33E0F0",
                    "0x33E150",
                )
            },
            {
                "0x33E050": "术语事典",
                "0x33E068": "机体图鉴",
                "0x33E078": "＜作品排序＞",
                "0x33E088": "＜名称排序＞",
                "0x33E0A0": "角色事典",
                "0x33E0B8": "登场作品",
                "0x33E0C8": "全长",
                "0x33E0D0": "重量",
                "0x33E0E8": "昵称",
                "0x33E0F0": "声优",
                "0x33E150": "角色事典",
            },
        )
        self.assertEqual(
            {
                offset: self.remaining["slps_context_ui_by_offset"].get(
                    offset
                )
                for offset in ("0x33E0DA", "0x33E0E2", "0x33E0FA", "0x33E112")
            },
            {
                "0x33E0DA": "表情",
                "0x33E0E2": "台词",
                "0x33E0FA": "返回",
                "0x33E112": "切换术语",
            },
        )

    def test_detail_work_title_slots_reuse_all_canonical_translations(self):
        references = self.remaining[
            "compdata_library_work_titles_by_offset"
        ]
        canonical = {
            entry["id"]: entry for entry in self.work_titles["entries"]
        }
        self.assertEqual(len(references), 22)
        self.assertEqual(
            {reference["title_id"] for reference in references.values()},
            set(canonical),
        )
        decoded = decode_production(
            (PROJECT_ROOT / "work/disc/DATA/COMPDATA.BN").read_bytes()
        ).output
        ranges = []
        for raw_offset, reference in sorted(
            references.items(), key=lambda item: int(item[0], 16)
        ):
            offset = int(raw_offset, 16)
            capacity = reference["capacity"]
            span = decoded[offset : offset + capacity]
            terminator = span.find(b"\0")
            self.assertGreater(terminator, 0)
            self.assertFalse(any(span[terminator:]))
            self.assertEqual(
                span[:terminator].decode("cp932"),
                canonical[reference["title_id"]]["source_text"],
            )
            self.assertEqual(
                hashlib.sha256(span).hexdigest(),
                reference["source_span_sha256"],
            )
            ranges.append((offset, offset + capacity))
        self.assertTrue(
            all(end <= next_start for (_, end), (next_start, _) in zip(ranges, ranges[1:]))
        )
        self.assertEqual(
            references["0x71D90"]["title_id"],
            "auto-demo/title/13",
        )

    def test_character_body_reflow_fills_lines_without_orphan_punctuation(self):
        text = (
            "不依赖他人、凭自身力量在荒废世界中生存的少年。"
            "15岁。虽是战争孤儿，却拥有不显悲壮的开朗积极性格。"
        )
        reflowed, widths = reflow_body(text, 16)
        lines = reflowed.splitlines()
        self.assertEqual("".join(lines), text)
        self.assertEqual(
            lines[:3],
            [
                "不依赖他人、凭自身力量在荒废世界",
                "中生存的少年。15岁。虽是战争孤",
                "儿，却拥有不显悲壮的开朗积极性",
            ],
        )
        self.assertTrue(all(width <= 16 for width in widths))
        self.assertTrue(all(width >= 15 for width in widths[:-1]))
        self.assertTrue(all(line[0] not in CLOSING for line in lines))
        self.assertTrue(all(line[-1] not in OPENING for line in lines))

    def test_library_menu_builds_all_six_labels_in_both_states(self):
        contract = self.library_scope["library_menu_tim2"]
        source = (PROJECT_ROOT / "work/disc/DATA/JTIM.BIN").read_bytes()
        font_flavor = json.loads(
            (
                PROJECT_ROOT
                / contract["writeback"]["font_flavor"]
            ).read_text(encoding="utf-8")
        )
        font_lock = json.loads(
            (
                PROJECT_ROOT
                / font_flavor["primary"]["font_lock"]
            ).read_text(encoding="utf-8")
        )
        font_path = PROJECT_ROOT / font_lock["font"]["path"]
        output, report = build_jtim_library_menu(
            source,
            contract,
            font_path=font_path,
        )
        self.assertEqual(len(output), len(source))
        self.assertNotEqual(output, source)
        self.assertEqual(len(report["labels"]), 12)
        self.assertEqual(
            {label["translation"] for label in report["labels"]},
            set(contract["labels"].values()),
        )
        self.assertTrue(report["tim2_metadata_preserved"])
        self.assertTrue(report["clut_and_non_image_bytes_preserved"])


if __name__ == "__main__":
    unittest.main()
