from __future__ import annotations

import hashlib
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Match the command-line entry point's tools/srwz import environment.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from tools import build_full_story_components as full_components
from tools import build_text_update_iso
from tools import prepare_zh_release_font


class TextUpdateIsoTests(unittest.TestCase):
    def test_release_proof_is_opt_in(self):
        with patch.object(sys, "argv", ["build_text_update_iso.py"]):
            args = build_text_update_iso.parse_args()
        self.assertFalse(args.release_proof)

        with patch.object(
            sys,
            "argv",
            ["build_text_update_iso.py", "--release-proof"],
        ):
            args = build_text_update_iso.parse_args()
        self.assertTrue(args.release_proof)

    def test_original_iso_proof_reuses_only_exact_file_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "original.iso"
            source.write_bytes(b"original")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            manifest = root / "original-disc.json"
            manifest.write_text(
                json.dumps(
                    {"disc": {"file_size": source.stat().st_size, "sha256": digest}}
                ),
                encoding="utf-8",
            )
            cache = root / "work/cache/original.json"
            commands = []
            reference = {
                "path": "original.iso",
                "size": source.stat().st_size,
                "sha256": digest,
            }
            with (
                patch.object(build_text_update_iso, "PROJECT_ROOT", root),
                patch.object(
                    build_text_update_iso,
                    "ORIGINAL_DISC_MANIFEST",
                    manifest,
                ),
                patch.object(
                    build_text_update_iso,
                    "_run_python",
                    side_effect=lambda command: commands.append(command),
                ),
            ):
                first = build_text_update_iso._verify_original_iso(
                    source, reference, cache_path=cache
                )
                second = build_text_update_iso._verify_original_iso(
                    source, reference, cache_path=cache
                )
                source.write_bytes(b"changed!")
                third = build_text_update_iso._verify_original_iso(
                    source, reference, cache_path=cache
                )
            self.assertFalse(first["reused"])
            self.assertTrue(second["reused"])
            self.assertFalse(third["reused"])
            self.assertEqual(len(commands), 2)

    def test_font_binary_signature_ignores_only_text_selection(self):
        first = {"assignments": [{"character": "中"}], "ui_selection": {"a": 1}}
        second = {"assignments": [{"character": "中"}], "ui_selection": {"a": 2}}
        changed = {"assignments": [{"character": "文"}], "ui_selection": {"a": 2}}
        self.assertEqual(
            build_text_update_iso._font_binary_signature(first),
            build_text_update_iso._font_binary_signature(second),
        )
        self.assertNotEqual(
            build_text_update_iso._font_binary_signature(first),
            build_text_update_iso._font_binary_signature(changed),
        )

    def test_release_assignment_mapping_matches_integrated_builder(self):
        assignments = [
            {"character": "文", "code": "8141", "glyph_index": 1},
            {"character": "中", "code": "8140", "glyph_index": 0},
        ]
        self.assertEqual(
            build_text_update_iso._assignment_mapping_sha256(assignments),
            full_components.sha256_bytes(
                json.dumps(
                    [("中", "8140", 0), ("文", "8141", 1)],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            ),
        )

    def test_font_raster_cache_requires_exact_binary_inputs(self):
        metadata = {
            "font_source": {"sha256": "a" * 64},
            "font_flavor": {"id": "regular"},
            "unsupported_character_fallbacks": [],
            "rasterizer": {"point_size": 22},
        }
        raster = {"packed_glyph_sha256": "b" * 64}
        proposal = {
            **metadata,
            "allocation_registry": {"sha256": "c" * 64},
            "assignments": [{"character": "中", "raster": raster}],
            "surface_alias_assignments": [],
            "source_compatibility_assignments": [],
        }
        cached, _reason = prepare_zh_release_font._reusable_rasters(
            proposal,
            expected_metadata=metadata,
            allocation_sha256="c" * 64,
        )
        self.assertEqual(cached, {"中": raster})

        changed_metadata = {**metadata, "rasterizer": {"point_size": 23}}
        cached, reason = prepare_zh_release_font._reusable_rasters(
            proposal,
            expected_metadata=changed_metadata,
            allocation_sha256="c" * 64,
        )
        self.assertEqual(cached, {})
        self.assertIn("identity changed", reason)

    def test_untracked_production_json_is_rejected(self):
        completed = type("Completed", (), {"stdout": b"corpus/zh/local.json\0"})()
        with (
            patch.object(
                build_text_update_iso.subprocess,
                "run",
                return_value=completed,
            ),
            self.assertRaisesRegex(
                build_text_update_iso.TextUpdateBuildError,
                "production JSON is not tracked by Git",
            ),
        ):
            build_text_update_iso._assert_no_untracked_production_json()

    def test_untracked_editorial_json_is_outside_production(self):
        completed = type(
            "Completed",
            (),
            {"stdout": b"config/editorial/local-review.json\0"},
        )()
        with patch.object(
            build_text_update_iso.subprocess,
            "run",
            return_value=completed,
        ):
            build_text_update_iso._assert_no_untracked_production_json()

    def test_story_and_library_builds_use_independent_worker_counts(self):
        commands = []
        with patch.object(
            build_text_update_iso,
            "_run_python",
            side_effect=lambda command: commands.append(command),
        ):
            build_text_update_iso._rebuild_story_and_library(
                story_workers=3,
                library_workers=5,
                refresh_manifests=True,
            )
        story = next(command for command in commands if "build_story_component.py" in command[0])
        library = next(
            command for command in commands if "build_library_v02_component.py" in command[0]
        )
        self.assertEqual(story[story.index("--workers") + 1], "3")
        self.assertEqual(library[library.index("--workers") + 1], "5")
        self.assertIn("--refresh-manifest", library)

    def test_unchanged_story_and_library_are_not_invoked(self):
        commands = []
        with patch.object(
            build_text_update_iso,
            "_run_python",
            side_effect=lambda command: commands.append(command),
        ):
            report = build_text_update_iso._rebuild_story_and_library(
                story_workers=3,
                library_workers=5,
                refresh_manifests=False,
                build_story=False,
                build_library=False,
            )
        self.assertEqual(commands, [])
        self.assertEqual(
            report,
            {"story_rebuilt": False, "library_rebuilt": False},
        )

    def test_release_font_component_is_reused_only_after_locked_outputs_match(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = {}
            for name, payload in {
                "proposal.json": b"proposal",
                "font-validation.json": b"report",
                "SLPS_258.87": b"slps",
                "DATA/VT1.BIN": b"vt1",
            }.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
                files[name] = {
                    "path": name,
                    "size": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            manifest = {
                "proposal": files["proposal.json"],
                "font_component": {
                    "report": files["font-validation.json"],
                    "slps": files["SLPS_258.87"],
                    "vt1": files["DATA/VT1.BIN"],
                },
            }
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            release = {"outputs": {"manifest": "manifest.json"}}
            with patch.object(build_text_update_iso, "PROJECT_ROOT", root):
                current, _reason = (
                    build_text_update_iso._font_component_cache_is_current(release)
                )
                self.assertTrue(current)
                (root / "SLPS_258.87").write_bytes(b"changed")
                current, reason = (
                    build_text_update_iso._font_component_cache_is_current(release)
                )
            self.assertFalse(current)
            self.assertIn("SLPS_258.87", reason)

    def test_original_member_locks_reject_conflicting_tracked_contracts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first.json"
            second = root / "second.json"
            first.write_text(
                json.dumps(
                    {
                        "source": {
                            "path": "work/disc/DATA/MTV_PROS.BIN",
                            "size": 9056,
                            "sha256": "1" * 64,
                        }
                    }
                ),
                encoding="utf-8",
            )
            second.write_text(
                json.dumps(
                    {
                        "source": {
                            "path": "work/disc/DATA/MTV_PROS.BIN",
                            "size": 8352,
                            "sha256": "2" * 64,
                        }
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                build_text_update_iso.TextUpdateBuildError,
                "conflicting original-member locks",
            ):
                build_text_update_iso.collect_original_member_locks((first, second))

    def test_text_lock_refresh_is_explicit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            corpus = root / "corpus/zh/sample.json"
            corpus.parent.mkdir(parents=True)
            corpus.write_text('{"translation":"新文本"}\n', encoding="utf-8")
            config = root / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "input": {
                            "path": "corpus/zh/sample.json",
                            "size": 1,
                            "sha256": "0" * 64,
                        }
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(build_text_update_iso, "PROJECT_ROOT", root):
                with self.assertRaisesRegex(
                    build_text_update_iso.TextUpdateBuildError,
                    "rerun with --refresh-manifests",
                ):
                    build_text_update_iso._refresh_text_locks(
                        (config,), refresh=False
                    )
                changed = build_text_update_iso._refresh_text_locks(
                    (config,), refresh=True
                )
            self.assertEqual(changed, ["corpus/zh/sample.json"])
            reference = json.loads(config.read_text(encoding="utf-8"))["input"]
            payload = corpus.read_bytes()
            self.assertEqual(reference["size"], len(payload))
            self.assertEqual(reference["sha256"], hashlib.sha256(payload).hexdigest())

    def test_frozen_rendered_text_cannot_be_blindly_relocked(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            corpus = root / "corpus/zh/ui-atlas/sample.json"
            corpus.parent.mkdir(parents=True)
            corpus.write_text("{}\n", encoding="utf-8")
            config = root / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "input": {
                            "path": "corpus/zh/ui-atlas/sample.json",
                            "size": 1,
                            "sha256": "0" * 64,
                        }
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.object(build_text_update_iso, "PROJECT_ROOT", root),
                self.assertRaisesRegex(
                    build_text_update_iso.TextUpdateBuildError,
                    "asset review/refreeze workflow",
                ),
            ):
                build_text_update_iso._refresh_text_locks(
                    (config,), refresh=True
                )

    def test_release_menu_selection_lock_refresh_is_explicit(self):
        with tempfile.TemporaryDirectory() as temporary:
            corpus = Path(temporary) / "release-v0.3.json"
            entries = [
                {
                    "id": "menu/SLPS/00/0001",
                    "member": "SLPS",
                    "translation": "新文本",
                }
            ]
            corpus.write_text(
                json.dumps(
                    {
                        "expected": {"selection_sha256": "0" * 64},
                        "entries": entries,
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.object(
                    build_text_update_iso,
                    "RELEASE_MENU_CORPUS",
                    corpus,
                ),
                self.assertRaisesRegex(
                    build_text_update_iso.TextUpdateBuildError,
                    "rerun with --refresh-manifests",
                ),
            ):
                build_text_update_iso._refresh_release_menu_selection_lock(
                    refresh=False
                )
            with patch.object(
                build_text_update_iso,
                "RELEASE_MENU_CORPUS",
                corpus,
            ):
                changed = (
                    build_text_update_iso._refresh_release_menu_selection_lock(
                        refresh=True
                    )
                )
            self.assertTrue(changed)
            expected = hashlib.sha256(
                json.dumps(
                    entries,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            self.assertEqual(
                json.loads(corpus.read_text(encoding="utf-8"))["expected"][
                    "selection_sha256"
                ],
                expected,
            )

    def test_mtv_pros_endpoint_must_equal_archive_size(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            slps = root / "SLPS_258.87"
            archive = root / "DATA/MTV_PROS.BIN"
            archive.parent.mkdir(parents=True)
            archive.write_bytes(b"x" * 8352)
            executable = bytearray(build_text_update_iso.MTV_PROS_TABLE_END + 8)
            positions = range(
                build_text_update_iso.MTV_PROS_TABLE_START,
                build_text_update_iso.MTV_PROS_TABLE_END,
                4,
            )
            offsets = [index * 128 for index, _ in enumerate(positions)]
            offsets[-1] = 8352
            for position, offset in zip(positions, offsets):
                struct.pack_into("<I", executable, position, offset)
            slps.write_bytes(executable)
            with patch.object(build_text_update_iso, "PROJECT_ROOT", root):
                report = build_text_update_iso.verify_mtv_pros_endpoint(
                    slps, archive
                )
                self.assertTrue(report["exact"])
                self.assertEqual(report["final_offset"], 8352)
                struct.pack_into(
                    "<I",
                    executable,
                    tuple(positions)[-1],
                    9056,
                )
                slps.write_bytes(executable)
                with self.assertRaisesRegex(
                    build_text_update_iso.TextUpdateBuildError,
                    "endpoint=9056, archive size=8352",
                ):
                    build_text_update_iso.verify_mtv_pros_endpoint(slps, archive)

    def test_incremental_mtv_pros_change_closes_over_slps(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "world-history.json"
            source.write_text("{}\n", encoding="utf-8")
            prior = {
                "inputs": {
                    "original_release_mtv_pros": {
                        "path": "world-history.json",
                        "size": 1,
                        "sha256": "0" * 64,
                    }
                }
            }
            with patch.object(full_components, "PROJECT_ROOT", root):
                affected, reasons = full_components._plan_incremental_members(
                    baseline_config={},
                    current_config={},
                    baseline_remaining_ui={},
                    current_remaining_ui={},
                    prior_report=prior,
                )
            self.assertEqual(
                affected,
                {
                    full_components.SLPS_MEMBER,
                    full_components.MTV_PROS_MEMBER,
                },
            )
            self.assertIn("closure:slps-mtv-pros-layout", reasons)

    def test_validation_manifest_drift_is_metadata_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            current = root / "font-manifest.json"
            current.write_text("{}\n", encoding="utf-8")
            prior = {
                "inputs": {
                    "full_story_font_manifest": {
                        "path": "font-manifest.json",
                        "size": 1,
                        "sha256": "0" * 64,
                    }
                }
            }
            with patch.object(full_components, "PROJECT_ROOT", root):
                affected, reasons = full_components._plan_incremental_members(
                    baseline_config={},
                    current_config={},
                    baseline_remaining_ui={},
                    current_remaining_ui={},
                    prior_report=prior,
                )
            self.assertEqual(affected, set())
            self.assertEqual(reasons, ["input:full_story_font_manifest"])

    def test_text_component_command_uses_incremental_mode(self):
        arguments = build_text_update_iso._incremental_component_arguments(
            refresh_manifest=False
        )
        self.assertIn("--incremental", arguments)
        self.assertNotIn("--refresh-manifest", arguments)

        arguments = build_text_update_iso._incremental_component_arguments(
            refresh_manifest=True
        )
        self.assertIn("--incremental", arguments)
        self.assertIn("--refresh-manifest", arguments)

    def test_fixed_slps_incremental_patch_keeps_prior_mtv_pros_offsets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "remaining.json"
            source.write_text("{}\n", encoding="utf-8")
            config = {
                "remaining_ui": {
                    "translations": {
                        "path": "remaining.json",
                        "size": 1,
                        "sha256": "0" * 64,
                    }
                }
            }
            prior = {
                "inputs": {
                    "remaining_ui_translations": {
                        "path": "remaining.json",
                        "size": 1,
                        "sha256": "0" * 64,
                    }
                }
            }
            with patch.object(full_components, "PROJECT_ROOT", root):
                affected, reasons = full_components._plan_incremental_members(
                    baseline_config=config,
                    current_config=config,
                    baseline_remaining_ui={"slps_by_offset": {"1": "old"}},
                    current_remaining_ui={"slps_by_offset": {"1": "new"}},
                    prior_report=prior,
                )
            self.assertEqual(affected, {full_components.SLPS_MEMBER})
            self.assertEqual(reasons, ["remaining-ui:slps_by_offset"])


if __name__ == "__main__":
    unittest.main()
