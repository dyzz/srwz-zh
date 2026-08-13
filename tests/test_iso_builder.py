import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools.build_iso import (
    IsoBuildError,
    _sanitize_dump_xml,
    expected_shift_segments,
    load_config,
    tree_file_map,
    validate_component_output_binding,
    validate_directory_contract,
    validate_replacement_sector_budget,
    write_build_xml,
)
from tools.srwz.iso9660 import IsoMember


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RELEASE_CONFIG = (
    PROJECT_ROOT / "config/iso/zh-release-full-story-build.json"
)


class Mkps2isoBuildTests(unittest.TestCase):
    def test_working_component_binding_rejects_stale_live_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.json"
            source.write_text('{"version":1}\n', encoding="utf-8")
            source_data = source.read_bytes()
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "status": "validated",
                        "inputs": {
                            "config": {
                                "path": "source.json",
                                "size": len(source_data),
                                "sha256": hashlib.sha256(source_data).hexdigest(),
                            }
                        },
                        "outputs": {
                            "DATA/VT1.BIN": {
                                "path": "work/build/profile/components/DATA/VT1.BIN",
                                "size": 10,
                                "sha256": "a" * 64,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            config = {
                "require_component_output_binding": True,
                "require_current_component_input_binding": True,
                "component_validation_manifest": "manifest.json",
                "component_required_status": "validated",
                "replacements": [
                    {
                        "member": "DATA/VT1.BIN",
                        "source": "work/build/profile/components/DATA/VT1.BIN",
                        "size": 10,
                        "sha256": "a" * 64,
                    }
                ],
            }
            source.write_text('{"version":2}\n', encoding="utf-8")
            with patch("tools.build_iso.PROJECT_ROOT", root.resolve()):
                with self.assertRaisesRegex(
                    IsoBuildError,
                    "component input drift requires a component rebuild: config",
                ):
                    validate_component_output_binding(config)

    def test_component_binding_rejects_copied_lock_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "status": "validated",
                        "outputs": {
                            "DATA/VT1.BIN": {
                                "path": (
                                    "work/build/profile/components/"
                                    "DATA/VT1.BIN"
                                ),
                                "size": 10,
                                "sha256": "a" * 64,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            config = {
                "require_component_output_binding": True,
                "component_validation_manifest": "manifest.json",
                "component_required_status": "validated",
                "replacements": [
                    {
                        "member": "DATA/VT1.BIN",
                        "source": (
                            "work/build/profile/components/DATA/VT1.BIN"
                        ),
                        "size": 11,
                        "sha256": "a" * 64,
                    }
                ],
            }
            with patch("tools.build_iso.PROJECT_ROOT", root.resolve()):
                with self.assertRaisesRegex(
                    IsoBuildError,
                    "differs from component manifest",
                ):
                    validate_component_output_binding(config)

    def test_component_binding_rejects_an_incomplete_member_set(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "status": "validated",
                        "outputs": {
                            "DATA/STAGE.BIN": {},
                            "HEDBDY/HB.BIN": {},
                        },
                    }
                ),
                encoding="utf-8",
            )
            config = {
                "require_component_output_binding": True,
                "component_validation_manifest": "manifest.json",
                "component_required_status": "validated",
                "replacements": [{"member": "DATA/STAGE.BIN"}],
            }
            with patch("tools.build_iso.PROJECT_ROOT", root.resolve()):
                with self.assertRaisesRegex(
                    IsoBuildError,
                    "member set differs",
                ):
                    validate_component_output_binding(config)

    def test_sanitizes_non_utf8_volume_identifier(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "layout.xml"
            path.write_bytes(
                b'<iso_project><identifiers system="PLAYSTATION" '
                b'volume="\xff\xfe"/></iso_project>'
            )
            _sanitize_dump_xml(path, "SRWZ_ZH_RELEASE")
            self.assertEqual(
                path.read_text(encoding="utf-8"),
                '<iso_project><identifiers system="PLAYSTATION" '
                'volume="SRWZ_ZH_RELEASE"/></iso_project>',
            )

    def test_writes_absolute_staging_and_logo_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "base.xml"
            output = root / "build.xml"
            staging = root / "staging"
            base.write_text(
                '<iso_project><identifiers volume="OLD"/>'
                '<logo file="old.raw"/><layer>'
                '<directory_tree source="old"/></layer></iso_project>',
                encoding="utf-8",
            )
            write_build_xml(base, output, staging, "SRWZ_ZH_RELEASE")
            text = output.read_text(encoding="utf-8")
            self.assertIn('volume="SRWZ_ZH_RELEASE"', text)
            self.assertIn(f'file="{staging / "boot_logo.raw"}"', text)
            self.assertIn(f'source="{staging}"', text)

    def test_pins_member_lbas_without_padding_logical_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "base.xml"
            output = root / "build.xml"
            staging = root / "staging"
            base.write_text(
                '<iso_project><identifiers volume="OLD"/>'
                '<logo file="old.raw"/><layer>'
                '<directory_tree source="old">'
                '<file name="ROOT.BIN"/>'
                '<dir name="DATA"><file name="compdata.bn"/>'
                '<file name="NEXT.BIN" offs="1"/></dir>'
                '</directory_tree></layer></iso_project>',
                encoding="utf-8",
            )
            write_build_xml(
                base,
                output,
                staging,
                "SRWZ_ZH_RELEASE",
                {
                    "ROOT.BIN": 100,
                    "DATA/COMPDATA.BN": 200,
                    "DATA/NEXT.BIN": 271,
                },
            )
            text = output.read_text(encoding="utf-8")
            self.assertIn('<file name="ROOT.BIN" offs="100"/>', text)
            self.assertIn(
                '<file name="compdata.bn" offs="200"/>', text
            )
            self.assertIn('<file name="NEXT.BIN" offs="271"/>', text)

    def test_lba_pinning_rejects_xml_member_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "base.xml"
            output = root / "build.xml"
            staging = root / "staging"
            base.write_text(
                '<iso_project><identifiers volume="OLD"/>'
                '<logo file="old.raw"/><layer>'
                '<directory_tree source="old">'
                '<file name="ROOT.BIN"/>'
                '</directory_tree></layer></iso_project>',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                IsoBuildError,
                "member set differs while pinning LBAs",
            ):
                write_build_xml(
                    base,
                    output,
                    staging,
                    "SRWZ_ZH_RELEASE",
                    {"OTHER.BIN": 100},
                )

    def test_tree_member_map_is_case_insensitive_and_ignores_logo(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "DATA").mkdir()
            (root / "DATA/vt1.bin").write_bytes(b"x")
            (root / "boot_logo.raw").write_bytes(b"logo")
            self.assertEqual(
                tree_file_map(root),
                {"DATA/VT1.BIN": root / "DATA/vt1.bin"},
            )

    def test_current_release_config_pins_toolchain_and_fixed_lba(self):
        config = load_config(RELEASE_CONFIG)
        self.assertEqual(config["schema_version"], 2)
        self.assertEqual(config["profile_id"], "zh-release-full-story")
        self.assertEqual(config["toolchain"]["version"], "1.1.1")
        self.assertEqual(
            config["toolchain"]["license_spdx"],
            "GPL-2.0-only",
        )
        self.assertEqual(
            config["output"]["expected_pcsx2_v263_image_type"],
            "DVD",
        )
        self.assertTrue(
            config["layout"]["preserve_original_member_sector_allocations"]
        )
        self.assertEqual(
            expected_shift_segments(config),
            (("DATA/STAGE.BIN", 0),),
        )

    def test_explicit_shift_segments_are_validated(self):
        config = load_config(RELEASE_CONFIG)
        config["layout"]["shift_segments"] = [
            {"first_member": "A.BIN", "shift_sectors": 2},
            {"first_member": "B.BIN", "shift_sectors": 3},
        ]
        config["layout"][
            "preserve_original_member_sector_allocations"
        ] = False
        validate_directory_contract(config)
        self.assertEqual(
            expected_shift_segments(config),
            (("A.BIN", 2), ("B.BIN", 3)),
        )

    def test_shift_segments_must_be_monotonic(self):
        config = load_config(RELEASE_CONFIG)
        config["layout"]["shift_segments"] = [
            {"first_member": "A.BIN", "shift_sectors": 3},
            {"first_member": "B.BIN", "shift_sectors": 2},
        ]
        config["layout"][
            "preserve_original_member_sector_allocations"
        ] = False
        with self.assertRaisesRegex(IsoBuildError, "shift is invalid"):
            validate_directory_contract(config)

    def test_fixed_lba_sector_budget_rejects_member_growth(self):
        config = {
            "layout": {
                "preserve_original_member_sector_allocations": True,
                "shift_segments": [
                    {"first_member": "NEXT.BIN", "shift_sectors": 0}
                ],
            },
            "source_iso": {"size": 4096},
            "output": {"expected_size": 4096},
            "replacements": [{"member": "DATA/VT1.BIN", "size": 2049}],
        }
        image = SimpleNamespace(
            members=(
                IsoMember("DATA/VT1.BIN", 10, 2048, 0),
                IsoMember("NEXT.BIN", 11, 1, 0),
            )
        )
        with self.assertRaisesRegex(
            IsoBuildError,
            "exceeds original member sectors",
        ):
            validate_replacement_sector_budget(config, image)

    def test_fixed_lba_sector_budget_accepts_same_sector_count(self):
        config = {
            "layout": {
                "preserve_original_member_sector_allocations": True,
                "shift_segments": [
                    {"first_member": "NEXT.BIN", "shift_sectors": 0}
                ],
            },
            "source_iso": {"size": 4096},
            "output": {"expected_size": 4096},
            "replacements": [{"member": "DATA/VT1.BIN", "size": 2048}],
        }
        image = SimpleNamespace(
            members=(
                IsoMember("DATA/VT1.BIN", 10, 2047, 0),
                IsoMember("NEXT.BIN", 11, 1, 0),
            )
        )
        report = validate_replacement_sector_budget(config, image)
        self.assertTrue(report["enforced"])
        self.assertTrue(
            report["all_replacements_within_original_member_sectors"]
        )
        self.assertEqual(report["entries"][0]["candidate_sectors"], 1)

    def test_release_output_cannot_fall_back_into_work(self):
        config = load_config(RELEASE_CONFIG)
        invalid = copy.deepcopy(config)
        invalid["output"]["path"] = "work/iso/srwz-release.iso"
        with self.assertRaisesRegex(
            IsoBuildError,
            "must be under build/iso/v0.1.0",
        ):
            validate_directory_contract(invalid)

    def test_evidence_manifest_must_stay_under_manifests(self):
        config = load_config(RELEASE_CONFIG)
        invalid = copy.deepcopy(config)
        invalid["component_validation_manifest"] = (
            "work/review/component-validation.json"
        )
        with self.assertRaisesRegex(
            IsoBuildError,
            "component validation manifest must be under manifests/",
        ):
            validate_directory_contract(invalid)


if __name__ == "__main__":
    unittest.main()
