import copy
import json
import tempfile
import unittest
from pathlib import Path

from tools.build_canary_iso import (
    IsoBuildError,
    _sanitize_dump_xml,
    load_config,
    tree_file_map,
    validate_directory_contract,
    write_build_xml,
)


class Mkps2isoBuildTests(unittest.TestCase):
    def test_sanitizes_non_utf8_volume_identifier(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "layout.xml"
            path.write_bytes(
                b'<iso_project><identifiers system="PLAYSTATION" '
                b'volume="\\xff\\xfe"/></iso_project>'
            )
            _sanitize_dump_xml(path, "SRWZ_CANARY")
            self.assertEqual(
                path.read_text(encoding="utf-8"),
                '<iso_project><identifiers system="PLAYSTATION" '
                'volume="SRWZ_CANARY"/></iso_project>',
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
            write_build_xml(base, output, staging, "SRWZ_CANARY")
            text = output.read_text(encoding="utf-8")
            self.assertIn('volume="SRWZ_CANARY"', text)
            self.assertIn(f'file="{staging / "boot_logo.raw"}"', text)
            self.assertIn(f'source="{staging}"', text)

    def test_tree_member_map_is_case_insensitive_and_ignores_logo(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "DATA").mkdir()
            (root / "DATA" / "vt1.bin").write_bytes(b"x")
            (root / "boot_logo.raw").write_bytes(b"logo")
            self.assertEqual(
                tree_file_map(root),
                {"DATA/VT1.BIN": root / "DATA" / "vt1.bin"},
            )

    def test_repository_config_pins_licensed_ps2_toolchain(self):
        root = Path(__file__).resolve().parents[1]
        config = json.loads(
            (root / "config" / "iso" / "canary-build.json").read_text()
        )
        self.assertEqual(config["schema_version"], 2)
        self.assertEqual(config["toolchain"]["version"], "1.1.1")
        self.assertEqual(config["toolchain"]["license_spdx"], "GPL-2.0-only")
        self.assertEqual(
            config["output"]["expected_pcsx2_v263_image_type"],
            "DVD",
        )
        self.assertEqual(config["profile_id"], "canary-menu")
        self.assertEqual(
            config["output"]["path"],
            "build/iso/canary-menu/srwz-canary.iso",
        )
        validate_directory_contract(config)

    def test_iso_output_cannot_fall_back_into_work(self):
        root = Path(__file__).resolve().parents[1]
        config = json.loads(
            (root / "config" / "iso" / "canary-build.json").read_text()
        )
        invalid = copy.deepcopy(config)
        invalid["output"]["path"] = "work/iso/srwz-canary.iso"
        with self.assertRaisesRegex(
            IsoBuildError,
            "must be under build/iso/canary-menu",
        ):
            validate_directory_contract(invalid)

    def test_repository_iso_config_loads_with_directory_contract(self):
        root = Path(__file__).resolve().parents[1]
        config = load_config(
            root / "config" / "iso" / "canary-build.json"
        )
        self.assertEqual(config["profile_id"], "canary-menu")

    def test_component_and_iso_configs_share_profile_paths(self):
        root = Path(__file__).resolve().parents[1]
        iso_config = json.loads(
            (root / "config" / "iso" / "canary-build.json").read_text()
        )
        component_config = json.loads(
            (
                root
                / "config"
                / "canary"
                / "minimal-slps-font.json"
            ).read_text()
        )
        profile = json.loads(
            (
                root
                / "config"
                / "build-profiles"
                / "canary-menu.json"
            ).read_text()
        )
        self.assertEqual(iso_config["profile_id"], profile["profile_id"])
        self.assertEqual(
            {
                replacement["source"]
                for replacement in iso_config["replacements"]
            },
            {
                component_config["outputs"]["slps"],
                component_config["outputs"]["vt1"],
            },
        )


if __name__ == "__main__":
    unittest.main()
