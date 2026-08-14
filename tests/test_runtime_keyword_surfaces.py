import json
import struct
import unittest
from pathlib import Path

from tools.build_full_story_components import _full_story_overrides
from tools.srwz.codec import decode_production as decode
from tools.srwz.iso_layout import ExecutableOffsetSpec, read_executable_archive_offsets
from tools.srwz.runtime_keywords import (
    apply_compdata_keyword_names,
    apply_stage_keyword_popups,
    load_keyword_authority,
)
from tools.srwz.text import (
    load_text_table,
    normalize_original_fullwidth_ascii,
    normalize_two_byte_visible_spaces,
    original_fullwidth_ascii_overrides,
    project_runtime_text_table,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class RuntimeKeywordSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(
            (PROJECT_ROOT / "config/full-story-components.json").read_text(
                encoding="utf-8"
            )
        )
        cls.reference = cls.config["runtime_keywords"]
        cls.source_table = load_text_table(
            PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
        )
        font_manifest = json.loads(
            (PROJECT_ROOT / "manifests/zh-release-font-validation.json").read_text(
                encoding="utf-8"
            )
        )
        _path, primary, aliases, _report = _full_story_overrides(font_manifest)
        runtime_table = project_runtime_text_table(cls.source_table, primary)
        runtime_table = project_runtime_text_table(runtime_table, aliases)
        runtime_table = project_runtime_text_table(
            runtime_table,
            original_fullwidth_ascii_overrides(cls.source_table),
        )
        cls.authority = load_keyword_authority(
            (PROJECT_ROOT / cls.reference["catalog"]["path"]).read_bytes(),
            (
                PROJECT_ROOT / cls.reference["library_archive"]["path"]
            ).read_bytes(),
            (
                PROJECT_ROOT / cls.reference["original_executable"]["path"]
            ).read_bytes(),
            runtime_table,
            table_start=int(cls.reference["keyword_table_start"], 0),
            table_end=int(cls.reference["keyword_table_end"], 0),
        )

    def test_library_authority_covers_all_52_reviewed_words(self):
        self.assertEqual(len(self.authority.entries), 52)
        self.assertEqual(self.authority.entries[19].translation, "LOGOS")
        self.assertEqual(self.authority.entries[24].translation, "ZAFT")
        self.assertEqual(self.authority.entries[25].translation, "军械库一号")
        self.assertEqual(self.authority.entries[36].translation, "BLOCK WORD")
        self.assertEqual(self.authority.entries[51].translation, "荣耀之星")
        self.assertEqual(
            tuple(tuple(fields) for fields in self.authority.fields),
            (("WORD", "SRCE", "DSCR", "DSC2"),) * 52,
        )
        stored_fields = [
            field
            for fields in self.authority.fields
            for field in fields.values()
        ]
        self.assertEqual(len(stored_fields), 208)
        for field in stored_fields:
            self.assertNotIn(b"\x20", field.data, field.tag)
        self.assertIn(
            "Anti Earth Union \nGovernment",
            normalize_two_byte_visible_spaces(
                normalize_original_fullwidth_ascii(
                    self.authority.fields[8]["DSCR"].text or ""
                )
            ),
        )

    def test_compdata_list_labels_are_complete_and_idempotent(self):
        original = decode(
            (PROJECT_ROOT / "work/disc/DATA/COMPDATA.BN").read_bytes()
        ).output
        current = decode(
            (
                PROJECT_ROOT
                / "work/build/release-base-ui/components/DATA/COMPDATA.BN"
            ).read_bytes()
        ).output
        kwargs = {
            "runtime_base": int(self.reference["compdata_runtime_base"], 0),
            "pointer_table_offset": int(
                self.reference["compdata_pointer_table_offset"], 0
            ),
        }
        rewritten, report = apply_compdata_keyword_names(
            current,
            original,
            self.authority,
            self.source_table,
            self.reference,
            **kwargs,
        )
        reread, idempotent_report = apply_compdata_keyword_names(
            rewritten,
            original,
            self.authority,
            self.source_table,
            self.reference,
            **kwargs,
        )
        self.assertEqual(rewritten, reread)
        self.assertEqual(report["list_label_count"], 52)
        self.assertEqual(report["relocation_count"], 2)
        self.assertGreater(report["changed_byte_count"], 0)
        self.assertEqual(idempotent_report["changed_byte_count"], 0)
        pointers = struct.unpack_from(
            "<52I",
            rewritten,
            kwargs["pointer_table_offset"],
        )
        self.assertEqual(
            pointers[19],
            kwargs["runtime_base"] + 0x71FB8,
        )
        self.assertEqual(
            pointers[24],
            kwargs["runtime_base"] + 0x71FD0,
        )
        for pointer, fields in zip(pointers, self.authority.fields):
            offset = pointer - kwargs["runtime_base"]
            target = fields["WORD"].data + b"\0"
            self.assertEqual(rewritten[offset : offset + len(target)], target)
            self.assertNotIn(b"\x20", target[:-1])

    def test_all_77_stage_popup_copies_match_library(self):
        original = (PROJECT_ROOT / "work/disc/DATA/STAGE.BIN").read_bytes()
        current = (
            PROJECT_ROOT / "work/build/full-story-stage/components/DATA/STAGE.BIN"
        ).read_bytes()
        hb = (
            PROJECT_ROOT / "work/build/full-story-stage/components/HEDBDY/HB.BIN"
        ).read_bytes()
        rewritten, report = apply_stage_keyword_popups(
            current,
            original,
            hb,
            self.authority,
            self.source_table,
            self.reference,
            self.config["full_pilot_names"]["codec"],
        )
        verified, verify_report = apply_stage_keyword_popups(
            rewritten,
            original,
            hb,
            self.authority,
            self.source_table,
            self.reference,
            self.config["full_pilot_names"]["codec"],
            verify_only=True,
        )
        self.assertEqual(rewritten, verified)
        self.assertEqual(report["record_count"], 77)
        self.assertEqual(report["stage_chunk_count"], 44)
        self.assertEqual(report["field_reference_count"], 308)
        self.assertEqual(report["allocation_count"], 233)
        self.assertEqual(report["shared_reference_count"], 75)
        self.assertEqual(report["relocation_count"], 3)
        self.assertEqual(report["minimum_output_headroom"], 256)
        self.assertTrue(verify_report["all_four_fields_match_library"])

        offsets = read_executable_archive_offsets(
            hb,
            ExecutableOffsetSpec(
                name="STAGE",
                member="DATA/STAGE.BIN",
                table_start=30320,
                table_end=31144,
            ),
            len(current),
        )
        stage2_start, stage2_end = offsets[2:4]
        before_stage2 = decode(current[stage2_start:stage2_end]).output
        after_stage2 = decode(rewritten[stage2_start:stage2_end]).output
        # The story allocator owns bytes inside the old WORD allocation.  They
        # must survive while only the glossary pointer moves to 0xEAA6.
        self.assertEqual(
            before_stage2[0xE9E8:0xEA00],
            after_stage2[0xE9E8:0xEA00],
        )
        self.assertEqual(
            struct.unpack_from("<I", after_stage2, 0x64F0)[0],
            int(self.reference["stage_runtime_base"], 0) + 0xEAA6,
        )


if __name__ == "__main__":
    unittest.main()
