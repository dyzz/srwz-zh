from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zlib

from tools import build_full_story_components as builder
from tools.srwz.stage_title_snapshot import (
    PACKED_SIZE, StageTitleSnapshotError, freeze_indexes, load_frozen_titles,
    thaw_indexes,
)


ROOT = Path(__file__).resolve().parents[1]


class StageTitleSnapshotTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads((ROOT / "config/full-story-components.json").read_text())
        cls.graphics = cls.config["full_stage_titles"]["graphics"]
        cls.snapshot = json.loads((ROOT / cls.graphics["frozen_snapshot"]["path"]).read_text())
        cls.entries = json.loads((ROOT / "corpus/zh/menu/stage-names.json").read_text())["entries"]

    def test_all_reviewed_pixels_and_configuration_lock_match(self):
        frozen = load_frozen_titles(self.snapshot, self.entries[:107], self.graphics["raster"])
        self.assertEqual(len(frozen), 107)
        ref = self.graphics["frozen_snapshot"]
        raw = (ROOT / ref["path"]).read_bytes()
        self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()), (ref["size"], ref["sha256"]))
        for title in frozen:
            self.assertEqual(thaw_indexes(freeze_indexes(title["packed"])), title["packed"])

    def test_changed_title_requires_explicit_refreeze(self):
        entries = deepcopy(self.entries[:107])
        entries[20]["translation"] = "different title"
        with self.assertRaisesRegex(StageTitleSnapshotError, "text/identity drift"):
            load_frozen_titles(self.snapshot, entries, self.graphics["raster"])

    def test_changed_layout_requires_explicit_refreeze(self):
        policy = deepcopy(self.graphics["raster"])
        policy["latin_layout"]["letter_gap"] += 1
        with self.assertRaisesRegex(StageTitleSnapshotError, "policy drift"):
            load_frozen_titles(self.snapshot, self.entries[:107], policy)

    def test_reordered_or_missing_titles_are_rejected(self):
        for mutate in (lambda x: x["titles"].reverse(), lambda x: x["titles"].pop()):
            snapshot = deepcopy(self.snapshot)
            mutate(snapshot)
            with self.assertRaises(StageTitleSnapshotError):
                load_frozen_titles(snapshot, self.entries[:107], self.graphics["raster"])

    def test_corrupt_pixels_are_rejected(self):
        reference = deepcopy(self.snapshot["titles"][0]["packed_indexes"])
        reference["sha256"] = "0" * 64
        with self.assertRaisesRegex(StageTitleSnapshotError, "content drift"):
            thaw_indexes(reference)
        reference["zlib_base64"] = "not-base64!"
        with self.assertRaisesRegex(StageTitleSnapshotError, "malformed"):
            thaw_indexes(reference)

    def test_trailing_or_oversized_zlib_data_are_rejected(self):
        reference = freeze_indexes(bytes(PACKED_SIZE))
        for compressed in (zlib.compress(bytes(PACKED_SIZE + 1)),
                           zlib.compress(bytes(PACKED_SIZE)) + b"trailer"):
            reference["zlib_base64"] = base64.b64encode(compressed).decode("ascii")
            with self.assertRaisesRegex(StageTitleSnapshotError, "content drift"):
                thaw_indexes(reference)

    def test_changed_snapshot_invalidates_vt1_incremental_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            path = root / "snapshot.json"
            path.write_bytes(b"reviewed snapshot")
            with patch.object(builder, "PROJECT_ROOT", root):
                prior = {"inputs": {"stage_title_graphics_snapshot":
                                    builder._file_lock(path, path.read_bytes())}}
                path.write_bytes(b"different snapshot")
                affected, reasons = builder._plan_incremental_members(
                    baseline_config={}, current_config={},
                    baseline_remaining_ui={}, current_remaining_ui={},
                    prior_report=prior,
                )
        self.assertEqual(affected, {builder.VT1_MEMBER})
        self.assertIn("input:stage_title_graphics_snapshot", reasons)

    @unittest.skipUnless((ROOT / "work/disc/DATA/VT1.BIN").is_file(), "local original resources required")
    def test_production_replay_matches_reviewed_group_without_rasterizing(self):
        table = builder.load_text_table(ROOT / "vendor/upstream-python/project/tbl_all.json")
        descriptors = json.loads((ROOT / "vendor/upstream-python/project/menu_files.json").read_text())
        descriptor = next(item for item in descriptors if item["friendly_name"] == "Compdata")
        decoded = builder.decode((ROOT / "work/disc/DATA/COMPDATA.BN").read_bytes()).output
        parsed = builder.parse_menu_file(decoded, descriptor, table)
        vt1 = (ROOT / "work/disc/DATA/VT1.BIN").read_bytes()
        slps = (ROOT / "work/disc/SLPS_258.87").read_bytes()
        with patch.object(builder, "decode_glyph", side_effect=AssertionError("font access")), \
             patch.object(builder, "render_stage_title", create=True, side_effect=AssertionError("rasterization")), \
             patch("tools.srwz.stage_title_graphics.render_stage_title", side_effect=AssertionError("rasterization")):
            output, report = builder._apply_full_stage_title_graphics(
                slps, vt1, self.entries, decoded, parsed, self.graphics,
            )
        start, end = report["group_start"], report["group_end"]
        self.assertEqual(hashlib.sha256(output[start:end]).hexdigest(), self.snapshot["output_group_sha256"])
        self.assertEqual(output[:start], vt1[:start])
        self.assertEqual(output[end:], vt1[end:])
        self.assertEqual(report["build_mode"], "locked_indexed_snapshot")
        self.assertIs(report["normal_build_rasterization"], False)
        self.assertEqual(report["texture_entry_count"], 107)


if __name__ == "__main__":
    unittest.main()
