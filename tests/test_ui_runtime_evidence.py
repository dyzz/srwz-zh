import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.srwz.ui_runtime_evidence import (
    UiRuntimeEvidenceError,
    build_case_plan,
    build_session_probe,
    validate_committed_runtime_receipt,
    verify_runtime_evidence,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = PROJECT_ROOT / "config/runtime/ui-test-matrix.json"


def sha256_path(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class UiRuntimeEvidenceTests(unittest.TestCase):
    def _fixture(self, root):
        iso_path = root / "build/iso/test/test.iso"
        iso_path.parent.mkdir(parents=True)
        iso_path.write_bytes(b"exact candidate ISO fixture")
        workspace = root / "work/runtime/ui-cases/core/test"
        (workspace / "logs").mkdir(parents=True)
        (workspace / "screenshots").mkdir(parents=True)
        log_path = workspace / "logs/emulog.txt"
        log_path.write_text(
            "Image type  = DVD\n"
            "ELF cdrom0:\\\\SLPS_258.87;1 with entry point "
            "at 0x00100008 is executing.\n",
            encoding="utf-8",
        )
        plan = {
            "schema_version": 1,
            "matrix": {
                "matrix_id": "fixture-matrix",
                "config_sha256": "c" * 64,
                "plan_sha256": "b" * 64,
            },
            "case": {
                "case_id": "core/test",
                "purpose": "localization_acceptance",
                "scene_ids": ["title/main-menu"],
                "variant": None,
                "assertions": ["layout intact"],
            },
            "artifact": {
                "artifact_id": "fixture-artifact",
                "manifest": "manifests/fixture.json",
                "manifest_sha256": "a" * 64,
                "iso_path": "build/iso/test/test.iso",
                "iso_size": iso_path.stat().st_size,
                "iso_sha256": sha256_path(iso_path),
                "mapping": None,
            },
            "fixture": {
                "fixture_id": "fresh-boot",
                "kind": "fresh_boot",
                "status": "ready",
                "workspace_path": None,
                "sha256": None,
            },
            "emulator": {
                "name": "PCSX2",
                "version": "2.6.3",
                "pine_version": "PCSX2 v2.6.3",
                "architecture": "x86_64",
                "launch_mode": "nogui fastboot nofullscreen",
                "game_id": "SLPS-25887",
            },
            "workspace": {
                "root": "work/runtime/ui-cases/core/test",
                "session_probe": (
                    "work/runtime/ui-cases/core/test/session-probe.json"
                ),
            },
            "capture_points": [
                {
                    "capture_id": "fixture-screen",
                    "kind": "screenshot",
                    "state": "fixture state",
                    "phase": None,
                }
            ],
        }
        return plan, iso_path, workspace, log_path

    def test_current_title_case_plan_binds_route_artifact_and_capture_ids(self):
        plan, draft = build_case_plan(
            PROJECT_ROOT,
            MATRIX_PATH,
            "core/title-main-menu",
        )
        self.assertEqual(plan["status"], "prepared_runtime_not_executed")
        self.assertEqual(
            plan["artifact"]["iso_sha256"],
            "cc4575bdc94a71d79c3a40810308d4eb41f8d3f69f1fd40139e63c83fde038c0",
        )
        self.assertEqual(plan["fixture"]["fixture_id"], "fresh-boot")
        self.assertEqual(len(plan["case"]["route"]), 2)
        self.assertEqual(
            {capture["capture_id"] for capture in plan["capture_points"]},
            {
                "core-title-start-selected",
                "core-title-library-selected",
            },
        )
        self.assertEqual(draft["status"], "draft")
        self.assertEqual(draft["verdict"], "not_tested")

    def test_session_probe_requires_exact_iso_running_dvd_elf_and_no_tlb(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan, _, _, log_path = self._fixture(root)
            report = build_session_probe(
                root,
                plan,
                pine_version="PCSX2 v2.6.3",
                game_title="Super Robot Taisen Z",
                game_id="SLPS-25887",
                status_before=0,
                status_after=0,
                fresh_process=True,
                log_path=log_path,
            )
            self.assertEqual(report["status"], "passed")
            self.assertTrue(all(report["checks"].values()))
            self.assertEqual(
                report["artifact"]["iso_sha256"],
                plan["artifact"]["iso_sha256"],
            )

    def test_session_probe_rejects_tlb_miss(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan, _, _, log_path = self._fixture(root)
            with log_path.open("a", encoding="utf-8") as stream:
                stream.write(
                    "TLB Miss, pc=0x1c6ea0 addr=0xc9d631c8 [load]\n"
                )
            with self.assertRaisesRegex(
                UiRuntimeEvidenceError,
                "no_tlb_miss",
            ):
                build_session_probe(
                    root,
                    plan,
                    pine_version="PCSX2 v2.6.3",
                    game_title="Super Robot Taisen Z",
                    game_id="SLPS-25887",
                    status_before=0,
                    status_after=0,
                    fresh_process=True,
                    log_path=log_path,
                )

    def test_complete_draft_produces_hash_only_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan, _, workspace, log_path = self._fixture(root)
            probe = build_session_probe(
                root,
                plan,
                pine_version="PCSX2 v2.6.3",
                game_title="Super Robot Taisen Z",
                game_id="SLPS-25887",
                status_before=0,
                status_after=0,
                fresh_process=True,
                log_path=log_path,
            )
            probe_path = workspace / "session-probe.json"
            probe_path.write_text(
                json.dumps(probe, indent=2) + "\n",
                encoding="utf-8",
            )
            screenshot = workspace / "screenshots/fixture-screen.png"
            screenshot.write_bytes(b"PNG fixture bytes")
            draft = {
                "schema_version": 1,
                "status": "complete",
                "matrix_id": "fixture-matrix",
                "case_id": "core/test",
                "session_probe": (
                    "work/runtime/ui-cases/core/test/session-probe.json"
                ),
                "captures": [
                    {
                        "capture_id": "fixture-screen",
                        "kind": "screenshot",
                        "workspace_paths": [
                            "work/runtime/ui-cases/core/test/"
                            "screenshots/fixture-screen.png"
                        ],
                        "passed": True,
                        "notes": "",
                    }
                ],
                "assertions": [
                    {
                        "index": 1,
                        "text": "layout intact",
                        "passed": True,
                        "notes": "",
                    }
                ],
                "verdict": "passed",
                "known_limits": [],
            }
            with patch(
                "tools.srwz.ui_runtime_evidence.identify_dimensions",
                return_value=(1280, 960),
            ):
                receipt = verify_runtime_evidence(
                    root,
                    plan,
                    draft,
                    imagemagick="magick",
                )
            self.assertEqual(receipt["status"], "passed")
            self.assertEqual(receipt["verdict"], "passed")
            self.assertEqual(
                receipt["captures"][0]["images"][0]["sha256"],
                sha256_path(screenshot),
            )
            self.assertNotIn("bytes", receipt["captures"][0]["images"][0])

            receipt_path = (
                root
                / "manifests/runtime/ui-cases/core-test.json"
            )
            receipt_path.parent.mkdir(parents=True)
            receipt_path.write_text(
                json.dumps(receipt, indent=2) + "\n",
                encoding="utf-8",
            )
            lock = {
                "manifest": "manifests/runtime/ui-cases/core-test.json",
                "sha256": sha256_path(receipt_path),
            }
            projection = validate_committed_runtime_receipt(
                root,
                lock,
                matrix_id="fixture-matrix",
                matrix_plan_sha256="b" * 64,
                case=plan["case"],
                artifact=plan["artifact"],
                fixture=plan["fixture"],
                emulator=plan["emulator"],
                capture_points=plan["capture_points"],
                assertion_count=1,
            )
            self.assertEqual(projection["status"], "passed")
            self.assertEqual(projection["capture_count"], 1)

            receipt["matrix"]["plan_sha256"] = "0" * 64
            receipt_path.write_text(
                json.dumps(receipt, indent=2) + "\n",
                encoding="utf-8",
            )
            lock["sha256"] = sha256_path(receipt_path)
            with self.assertRaisesRegex(
                UiRuntimeEvidenceError,
                "identity drift",
            ):
                validate_committed_runtime_receipt(
                    root,
                    lock,
                    matrix_id="fixture-matrix",
                    matrix_plan_sha256="b" * 64,
                    case=plan["case"],
                    artifact=plan["artifact"],
                    fixture=plan["fixture"],
                    emulator=plan["emulator"],
                    capture_points=plan["capture_points"],
                    assertion_count=1,
                )

    def test_incomplete_or_failed_assertion_cannot_produce_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan, _, _, _ = self._fixture(root)
            draft = {
                "schema_version": 1,
                "status": "draft",
                "matrix_id": "fixture-matrix",
                "case_id": "core/test",
            }
            with self.assertRaisesRegex(
                UiRuntimeEvidenceError,
                "not complete",
            ):
                verify_runtime_evidence(
                    root,
                    plan,
                    draft,
                    imagemagick="magick",
                )

    def test_mapping_receipt_uses_locked_runtime_texture_delta(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan, _, workspace, log_path = self._fixture(root)
            plan = copy.deepcopy(plan)
            plan["artifact"]["mapping"] = {
                "chunk_index": 2,
                "changed_pixel_count": 299,
                "changed_pixel_indexes_sha256": "d" * 64,
            }
            plan["capture_points"] = [
                {
                    "capture_id": "fixture-texture",
                    "kind": "texture_delta",
                    "state": "locked mapping texture",
                    "phase": None,
                }
            ]
            probe = build_session_probe(
                root,
                plan,
                pine_version="PCSX2 v2.6.3",
                game_title="Super Robot Taisen Z",
                game_id="SLPS-25887",
                status_before=0,
                status_after=0,
                fresh_process=True,
                log_path=log_path,
            )
            probe_path = workspace / "session-probe.json"
            probe_path.write_text(
                json.dumps(probe, indent=2) + "\n",
                encoding="utf-8",
            )
            texture = workspace / "screenshots/runtime-texture.png"
            texture.write_bytes(b"texture PNG fixture")
            reference = workspace / "screenshots/reference.png"
            reference.write_bytes(b"reference PNG fixture")
            draft = {
                "schema_version": 1,
                "status": "complete",
                "matrix_id": "fixture-matrix",
                "case_id": "core/test",
                "session_probe": (
                    "work/runtime/ui-cases/core/test/session-probe.json"
                ),
                "captures": [
                    {
                        "capture_id": "fixture-texture",
                        "kind": "texture_delta",
                        "workspace_paths": [
                            "work/runtime/ui-cases/core/test/"
                            "screenshots/runtime-texture.png"
                        ],
                        "passed": True,
                        "notes": "",
                    }
                ],
                "assertions": [
                    {
                        "index": 1,
                        "text": "layout intact",
                        "passed": True,
                        "notes": "",
                    }
                ],
                "verdict": "passed",
                "known_limits": [],
            }
            delta = {
                "changed_pixel_count": 299,
                "changed_pixel_indexes_sha256": "d" * 64,
                "outside_mask_rgba_exact": True,
                "replacement_rgba_exact": True,
                "preserved_rgba_exact": True,
            }
            mask = {
                "x": 0,
                "y": 0,
                "width": 1,
                "height": 1,
                "replacement_rgba": "00000000",
                "preserve_rgba": ["00000000"],
            }
            with (
                patch(
                    "tools.srwz.ui_runtime_evidence.identify_dimensions",
                    return_value=(256, 256),
                ),
                patch(
                    "tools.srwz.ui_runtime_evidence._mapping_reference",
                    return_value=(
                        reference,
                        mask,
                        plan["artifact"]["mapping"],
                    ),
                ),
                patch(
                    "tools.srwz.ui_runtime_evidence.read_rgba8",
                    return_value=b"\0" * (256 * 256 * 4),
                ),
                patch(
                    "tools.srwz.ui_runtime_evidence.verify_masked_rgba",
                    return_value=delta,
                ),
            ):
                receipt = verify_runtime_evidence(
                    root,
                    plan,
                    draft,
                    imagemagick="magick",
                )
            self.assertEqual(
                receipt["captures"][0]["texture_delta"][
                    "changed_pixel_count"
                ],
                299,
            )
            self.assertEqual(
                receipt["captures"][0]["texture_delta"][
                    "changed_pixel_indexes_sha256"
                ],
                "d" * 64,
            )

    def test_memory_card_session_probe_checks_actual_fixture_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan, _, _, log_path = self._fixture(root)
            card = (
                root
                / "work/runtime/ui-fixtures/first-intermission/"
                "SLPS-25887.ps2"
            )
            card.parent.mkdir(parents=True)
            card.write_bytes(b"native memory card fixture")
            plan = copy.deepcopy(plan)
            plan["fixture"] = {
                "fixture_id": "first-intermission-card",
                "kind": "memory_card",
                "status": "ready",
                "workspace_path": (
                    "work/runtime/ui-fixtures/first-intermission/"
                    "SLPS-25887.ps2"
                ),
                "sha256": "0" * 64,
            }
            with self.assertRaisesRegex(
                UiRuntimeEvidenceError,
                "memory-card SHA-256 drift",
            ):
                build_session_probe(
                    root,
                    plan,
                    pine_version="PCSX2 v2.6.3",
                    game_title="Super Robot Taisen Z",
                    game_id="SLPS-25887",
                    status_before=0,
                    status_after=0,
                    fresh_process=True,
                    log_path=log_path,
                )


if __name__ == "__main__":
    unittest.main()
