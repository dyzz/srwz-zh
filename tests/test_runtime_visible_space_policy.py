import json
import unittest
from pathlib import Path

from tools import build_full_story_components
from tools.srwz.codec import decode_production as decode
from tools.srwz.display_names import load_display_name_source
from tools.srwz.image_export import parse_seg_offsets
from tools.srwz.iso_layout import (
    CORE_ARCHIVE_SPECS,
    ExecutableOffsetSpec,
    read_executable_archive_offsets,
)
from tools.srwz.menu import parse_menu_file
from tools.srwz.srvc import parse_srvc_archive
from tools.srwz.stage_overview import parse_stage_overviews
from tools.srwz.summary import parse_summary
from tools.srwz.text import (
    decode_text,
    load_text_table,
    original_fullwidth_ascii_overrides,
    project_runtime_text_table,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class RuntimeVisibleSpacePolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(
            (PROJECT_ROOT / "config/full-story-components.json").read_text(
                encoding="utf-8"
            )
        )
        manifest = json.loads(
            (
                PROJECT_ROOT
                / "manifests/full-story-components-validation.json"
            ).read_text(encoding="utf-8")
        )
        outputs = manifest["outputs"]
        cls.compdata = decode(
            (PROJECT_ROOT / outputs["DATA/COMPDATA.BN"]["path"]).read_bytes()
        ).output
        cls.slps = (
            PROJECT_ROOT / outputs["SLPS_258.87"]["path"]
        ).read_bytes()
        cls.hb = (
            PROJECT_ROOT / outputs["HEDBDY/HB.BIN"]["path"]
        ).read_bytes()
        cls.stage = (
            PROJECT_ROOT / outputs["DATA/STAGE.BIN"]["path"]
        ).read_bytes()
        cls.srvc = (
            PROJECT_ROOT / outputs["BTL/SRVC.BIN"]["path"]
        ).read_bytes()
        cls.srvc_seg = (
            PROJECT_ROOT / outputs["BTL/SRVC.SEG"]["path"]
        ).read_bytes()
        cls.mtv_pros = (
            PROJECT_ROOT / outputs["DATA/MTV_PROS.BIN"]["path"]
        ).read_bytes()

        reference = cls.config["full_pilot_names"]
        structure, _data, _names, _context = load_display_name_source(
            PROJECT_ROOT,
            PROJECT_ROOT / reference["structure"]["path"],
        )
        table = load_text_table(
            PROJECT_ROOT / structure["text_table"]["path"]
        )
        font_reference = cls.config["full_story_font"]["manifest"]
        font_manifest = json.loads(
            (PROJECT_ROOT / font_reference["path"]).read_text(encoding="utf-8")
        )
        _proposal, primary, aliases, _report = (
            build_full_story_components._full_story_overrides(font_manifest)
        )
        output_table = project_runtime_text_table(table, primary)
        output_table = project_runtime_text_table(output_table, aliases)
        cls.output_table = project_runtime_text_table(
            output_table,
            original_fullwidth_ascii_overrides(table),
        )

    def test_compdata_menu_targets_have_no_raw_visible_spaces(self):
        descriptors = json.loads(
            (
                PROJECT_ROOT
                / "vendor/upstream-python/project/menu_files.json"
            ).read_text(encoding="utf-8")
        )
        descriptor = next(
            item
            for item in descriptors
            if item.get("friendly_name") == "Compdata"
        )
        parsed = parse_menu_file(
            self.compdata, descriptor, self.output_table
        )
        seen_offsets = set()
        for entry in parsed.entries:
            for offset in entry.target_offsets:
                if offset in seen_offsets:
                    continue
                seen_offsets.add(offset)
                stored = decode_text(
                    self.compdata, offset, self.output_table
                )
                payload = self.compdata[offset : offset + stored.consumed]
                self.assertNotIn(b"\x20", payload, entry.entry_id)

    def test_stage_overviews_have_no_raw_visible_spaces(self):
        offsets = read_executable_archive_offsets(
            self.hb,
            ExecutableOffsetSpec(
                name="HEDBDY/HB.BIN STAGE offsets",
                member="HEDBDY/HB.BIN",
                table_start=30320,
                table_end=31144,
            ),
            len(self.stage),
        )
        decoded = decode(self.stage[offsets[0] : offsets[1]]).output
        for entry in parse_stage_overviews(decoded, self.output_table):
            payload = decoded[
                entry.text_offset : entry.text_offset + entry.encoded_size
            ]
            self.assertNotIn(b"\x20", payload, entry.entry_id)

    def test_world_history_has_no_raw_visible_spaces(self):
        offsets = read_executable_archive_offsets(
            self.slps,
            CORE_ARCHIVE_SPECS["MTV_PROS.BIN"],
            len(self.mtv_pros),
        )
        seen = 0
        for chunk_index, (start, end) in enumerate(
            zip(offsets, offsets[1:])
        ):
            decoded = decode(self.mtv_pros[start:end]).output
            parsed = parse_summary(
                decoded,
                self.output_table,
                chunk_index=chunk_index,
            )
            for entry in parsed.entries:
                payload = decoded[
                    entry.text_offset : entry.text_offset + entry.allocated_length
                ]
                self.assertNotIn(b"\x20", payload, entry.entry_id)
                seen += 1
        self.assertEqual(seen, 28)

    def test_srvc_records_have_no_raw_spaces_or_json_fragment_pollution(self):
        chunks = parse_srvc_archive(
            self.srvc,
            parse_seg_offsets(self.srvc_seg, len(self.srvc)),
            self.output_table,
        )
        for chunk in chunks:
            for record in chunk.records:
                payload = self.srvc[
                    record.archive_text_start : record.archive_text_end
                ]
                label = f"{chunk.chunk_index}/{record.record_index}"
                self.assertNotIn(b"\x20", payload, label)
                self.assertNotIn("}]}  {", record.text, label)

    def test_srvc_corpus_has_no_json_fragment_pollution(self):
        path = PROJECT_ROOT / self.config["srvc_battle_text"]["corpus"]["path"]
        document = json.loads(path.read_text(encoding="utf-8"))
        for entry in document["entries"]:
            self.assertNotIn("}]}  {", entry["translation"], entry["id"])


if __name__ == "__main__":
    unittest.main()
