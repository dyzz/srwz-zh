import hashlib
import json
import plistlib
import tempfile
import unittest
from pathlib import Path

from tools.srwz.pcsx2_session import (
    Pcsx2SessionError,
    collect_pcsx2_session,
    prepare_pcsx2_session,
    register_pcsx2_savestate,
    sha256_file,
    validate_pcsx2_session,
    verify_savestate_receipt,
    with_exploratory_iso,
)


class Pcsx2SessionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.iso = self.root / "build/iso/test/test.iso"
        self.iso.parent.mkdir(parents=True)
        self.iso.write_bytes(b"exact test iso")

        self.app = self.root / "source/PCSX2.app"
        binary = self.app / "Contents/MacOS/PCSX2"
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"fake PCSX2 v2.6.3")
        binary.chmod(0o755)
        info = {
            "CFBundleIdentifier": "net.pcsx2.pcsx2",
            "CFBundleShortVersionString": "v2.6.3",
        }
        (self.app / "Contents/Info.plist").write_bytes(
            plistlib.dumps(info)
        )

        self.settings = self.root / "source/PCSX2.ini"
        self.settings.write_text(
            "[Folders]\n"
            "Bios = bios\n"
            "[EmuCore]\n"
            "EnablePINE = false\n"
            "[MemoryCards]\n"
            "Slot1_Enable = true\n"
            "Slot1_Filename = system-card.ps2\n"
            "Slot2_Enable = true\n"
            "Slot2_Filename = system-card-2.ps2\n",
            encoding="utf-8",
        )
        self.bios = self.root / "source/bios"
        self.bios.mkdir()
        (self.bios / "bios.bin").write_bytes(b"owned BIOS fixture")

    def tearDown(self):
        self.temporary.cleanup()

    def _plan(self, fixture):
        return {
            "artifact": {
                "artifact_id": "test-artifact",
                "manifest": "manifests/test.json",
                "manifest_sha256": "0" * 64,
                "iso_path": "build/iso/test/test.iso",
                "iso_size": self.iso.stat().st_size,
                "iso_sha256": sha256_file(self.iso),
            },
            "fixture": fixture,
            "emulator": {
                "name": "PCSX2",
                "version": "2.6.3",
                "pine_version": "PCSX2 v2.6.3",
                "architecture": "x86_64",
            },
            "case": {
                "case_id": "core/test",
                "purpose": "localization_acceptance",
                "route": ["Reach the test surface."],
                "assertions": ["The localized label is visible."],
            },
        }

    def _card(self, name="candidate.ps2"):
        card = self.root / "source" / name
        data = bytearray(1024)
        signature = b"Sony PS2 Memory Card Format"
        data[: len(signature)] = signature
        marker = b"BISLPS-25887"
        data[128 : 128 + len(marker)] = marker
        card.write_bytes(data)
        return card

    def _prepare(self, plan, session_id, **kwargs):
        return prepare_pcsx2_session(
            self.root,
            plan,
            session_id=session_id,
            pcsx2_app=self.app,
            settings_template=self.settings,
            bios_directory=self.bios,
            architecture_reader=lambda _: ("x86_64",),
            **kwargs,
        )

    def test_fresh_boot_has_no_system_memory_card_or_savestate(self):
        plan = self._plan(
            {
                "fixture_id": "fresh-boot",
                "kind": "fresh_boot",
                "status": "ready",
                "workspace_path": None,
                "sha256": None,
            }
        )
        lock_path, launch_path = self._prepare(
            plan,
            "fresh-session",
        )
        lock = validate_pcsx2_session(self.root, lock_path)
        self.assertTrue(launch_path.is_file())
        self.assertEqual(lock["launch"]["boot_source"], "fresh_boot")
        self.assertIsNone(lock["portable"]["memory_card"])
        self.assertIsNone(lock["portable"]["savestate"])
        self.assertTrue(
            lock["evidence"]["primary_runtime_receipt_allowed"]
        )
        workspace = lock_path.parent
        self.assertEqual(list((workspace / "memcards").iterdir()), [])
        self.assertTrue((workspace / "bios").is_symlink())
        settings = (
            workspace / "session-inputs/PCSX2.ini"
        ).read_text()
        self.assertIn("EnablePINE = true", settings)
        self.assertIn("McdFolderAutoManage = false", settings)
        self.assertIn("Slot1_Enable = false", settings)
        self.assertIn("Slot2_Enable = false", settings)

    def test_unpromoted_card_requires_explicit_exploration_scope(self):
        card = self._card()
        plan = self._plan(
            {
                "fixture_id": "first-intermission-card",
                "kind": "memory_card",
                "status": "not_acquired",
                "workspace_path": (
                    "work/runtime/ui-fixtures/first-intermission/"
                    "SLPS-25887.ps2"
                ),
                "sha256": None,
            }
        )
        with self.assertRaisesRegex(
            Pcsx2SessionError,
            "exploration candidate",
        ):
            self._prepare(
                plan,
                "unsafe-session",
                memory_card=card,
            )
        lock_path, _ = self._prepare(
            plan,
            "explore-session",
            memory_card=card,
            exploratory=True,
        )
        lock = validate_pcsx2_session(self.root, lock_path)
        copied = (
            self.root
            / lock["portable"]["runtime_memory_card_path"]
        )
        self.assertNotEqual(copied.resolve(), card.resolve())
        self.assertEqual(copied.read_bytes(), card.read_bytes())
        self.assertFalse(
            lock["evidence"]["primary_runtime_receipt_allowed"]
        )

    def test_state_bundle_locks_iso_binary_and_current_card_snapshot(self):
        card = self._card()
        plan = self._plan(
            {
                "fixture_id": "first-intermission-card",
                "kind": "memory_card",
                "status": "ready",
                "workspace_path": (
                    "work/runtime/ui-fixtures/first-intermission/"
                    "SLPS-25887.ps2"
                ),
                "sha256": sha256_file(card),
            }
        )
        lock_path, _ = self._prepare(
            plan,
            "card-session",
            memory_card=card,
        )
        isolated_card = lock_path.parent / "memcards/Mcd001.ps2"
        isolated_card.write_bytes(isolated_card.read_bytes() + b"game write")
        state_path = (
            lock_path.parent
            / "sstates/SLPS-25887 (01234567).01.p2s"
        )
        state_path.write_bytes(b"state" * 512)
        receipt_path = register_pcsx2_savestate(
            self.root,
            lock_path,
            state_path,
            state_id="intermission-main",
        )
        receipt = verify_savestate_receipt(self.root, receipt_path)
        self.assertEqual(
            receipt["status"],
            "hash_locked_acceleration_only",
        )
        self.assertEqual(receipt["acceptance_scope"], "acceleration_only")
        frozen_card = (
            self.root / receipt["memory_card_snapshot"]["path"]
        )
        self.assertEqual(frozen_card.read_bytes(), isolated_card.read_bytes())

        state_lock_path, _ = self._prepare(
            plan,
            "state-session",
            savestate_receipt=receipt_path,
            exploratory=True,
        )
        state_lock = validate_pcsx2_session(
            self.root,
            state_lock_path,
        )
        self.assertEqual(
            state_lock["launch"]["boot_source"],
            "savestate",
        )
        self.assertIn("-statefile", state_lock["launch"]["argv"])
        self.assertFalse(
            state_lock["evidence"]["primary_runtime_receipt_allowed"]
        )

    def test_savestate_receipt_fails_after_iso_drift(self):
        card = self._card()
        plan = self._plan(
            {
                "fixture_id": "first-intermission-card",
                "kind": "memory_card",
                "status": "ready",
                "workspace_path": "work/runtime/ui-fixtures/card.ps2",
                "sha256": sha256_file(card),
            }
        )
        lock_path, _ = self._prepare(
            plan,
            "drift-source",
            memory_card=card,
        )
        state_path = lock_path.parent / "sstates/state.p2s"
        state_path.write_bytes(b"x" * 2048)
        receipt_path = register_pcsx2_savestate(
            self.root,
            lock_path,
            state_path,
            state_id="drift-check",
        )
        self.iso.write_bytes(b"changed iso")
        with self.assertRaisesRegex(Pcsx2SessionError, "savestate ISO"):
            verify_savestate_receipt(self.root, receipt_path)

    def test_file_hash_is_streaming_and_exact(self):
        path = self.root / "source/hash.bin"
        path.write_bytes(b"abc")
        self.assertEqual(
            sha256_file(path),
            hashlib.sha256(b"abc").hexdigest(),
        )

    def test_exploratory_iso_override_is_exact_but_unpromoted(self):
        plan = self._plan(
            {
                "fixture_id": "fresh-boot",
                "kind": "fresh_boot",
                "status": "ready",
                "workspace_path": None,
                "sha256": None,
            }
        )
        alternate = self.root / "build/iso/lab/lab.iso"
        alternate.parent.mkdir(parents=True)
        alternate.write_bytes(b"exploratory")
        copied = with_exploratory_iso(self.root, plan, alternate)
        self.assertEqual(
            copied["artifact"]["matrix_artifact_id"],
            "test-artifact",
        )
        self.assertTrue(copied["artifact"]["exploratory_override"])
        self.assertEqual(
            copied["artifact"]["iso_sha256"],
            sha256_file(alternate),
        )
        self.assertEqual(plan["artifact"]["artifact_id"], "test-artifact")

    def test_collection_copies_stable_log_and_screenshots_to_case(self):
        plan = self._plan(
            {
                "fixture_id": "fresh-boot",
                "kind": "fresh_boot",
                "status": "ready",
                "workspace_path": None,
                "sha256": None,
            }
        )
        lock_path, _ = self._prepare(plan, "collect-session")
        session_root = lock_path.parent
        lock = validate_pcsx2_session(self.root, lock_path)
        (self.root / lock["launch"]["log_path"]).write_text(
            "Image type = DVD\nELF SLPS_258.87 is executing.\n",
            encoding="utf-8",
        )
        (session_root / "snaps/frame.png").write_bytes(b"fake png")
        report_path = collect_pcsx2_session(self.root, lock_path)
        report = json.loads(report_path.read_text())
        self.assertEqual(report["status"], "collected_unreviewed")
        self.assertEqual(report["case_id"], "core/test")
        self.assertEqual(len(report["screenshots"]), 1)
        self.assertTrue(
            (
                report_path.parent
                / "logs/emulog.txt"
            ).is_file()
        )


if __name__ == "__main__":
    unittest.main()
