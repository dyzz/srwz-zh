import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools.build_ui_iso_step import (
    SingleIsoCandidateError,
    cleanup_full_disc_workspaces,
    generated_iso_paths,
    load_selected_step,
    remove_existing_isos,
    validate_slps_vt1_pair,
)
from tools.srwz.font import GLYPH_COUNT, GLYPH_SIZE


class SingleIsoCandidateTests(unittest.TestCase):
    def test_selects_exact_incremental_step(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chain.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "steps": [
                            {"step_id": "baseline"},
                            {"step_id": "atlas"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                load_selected_step(path, "atlas")["step_id"],
                "atlas",
            )
            with self.assertRaisesRegex(
                SingleIsoCandidateError,
                "exist exactly once",
            ):
                load_selected_step(path, "missing")

    def test_refuses_to_accumulate_isos_without_explicit_replace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "build/iso/first/first.iso"
            second = root / "build/iso/second/second.iso"
            first.parent.mkdir(parents=True)
            second.parent.mkdir(parents=True)
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            self.assertEqual(generated_iso_paths(root), (first, second))
            with self.assertRaisesRegex(
                SingleIsoCandidateError,
                "--replace-existing",
            ):
                remove_existing_isos(root, replace_existing=False)
            self.assertEqual(
                remove_existing_isos(root, replace_existing=True),
                (first, second),
            )
            self.assertEqual(generated_iso_paths(root), ())

    def test_prunes_only_exact_original_and_staging_workspaces(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / "work/build/profile/iso/original"
            staging = root / "work/build/profile/iso/staging"
            original.mkdir(parents=True)
            staging.mkdir(parents=True)
            (original / "member.bin").write_bytes(b"original")
            (staging / "member.bin").write_bytes(b"staging")
            expected = (original.resolve(), staging.resolve())
            removed = cleanup_full_disc_workspaces(
                root,
                {
                    "workspace": {
                        "original_tree": "work/build/profile/iso/original",
                        "staging_tree": "work/build/profile/iso/staging",
                    }
                },
            )
            self.assertEqual(removed, expected)
            self.assertFalse(original.exists())
            self.assertFalse(staging.exists())

    def test_rejects_broad_workspace_cleanup_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(
                SingleIsoCandidateError,
                "unsafe full-disc workspace",
            ):
                cleanup_full_disc_workspaces(
                    root,
                    {
                        "workspace": {
                            "original_tree": "work/build/original",
                            "staging_tree": "work/build/staging",
                        }
                    },
                )

    def test_rejects_incompatible_slps_vt1_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            slps = root / "work/build/old/SLPS_258.87"
            vt1 = root / "work/build/new/DATA/VT1.BIN"
            slps.parent.mkdir(parents=True)
            vt1.parent.mkdir(parents=True)
            slps.write_bytes(b"old offsets")
            vt1.write_bytes(b"new archive")
            step = {
                "component_sources": {
                    "SLPS_258.87": "work/build/old/SLPS_258.87",
                    "DATA/VT1.BIN": "work/build/new/DATA/VT1.BIN",
                }
            }
            with (
                patch(
                    "tools.build_ui_iso_step.decode_vt1_font_segment",
                    side_effect=ValueError("invalid font slice"),
                ),
                self.assertRaisesRegex(
                    SingleIsoCandidateError,
                    "incompatible SLPS_258.87 offset table",
                ),
            ):
                validate_slps_vt1_pair(root, step)

    def test_accepts_matching_slps_vt1_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            slps = root / "work/build/pair/SLPS_258.87"
            vt1 = root / "work/build/pair/DATA/VT1.BIN"
            slps.parent.mkdir(parents=True)
            vt1.parent.mkdir(parents=True)
            slps.write_bytes(b"matching offsets")
            vt1.write_bytes(b"matching archive")
            step = {
                "component_sources": {
                    "SLPS_258.87": "work/build/pair/SLPS_258.87",
                    "DATA/VT1.BIN": "work/build/pair/DATA/VT1.BIN",
                }
            }
            expected_size = GLYPH_COUNT * GLYPH_SIZE
            with patch(
                "tools.build_ui_iso_step.decode_vt1_font_segment",
                return_value=SimpleNamespace(
                    decoded=b"\0" * expected_size,
                    compressed_size=123,
                ),
            ):
                report = validate_slps_vt1_pair(root, step)
            self.assertIsNotNone(report)
            self.assertEqual(report["decoded_size"], expected_size)
            self.assertEqual(report["compressed_size"], 123)


if __name__ == "__main__":
    unittest.main()
