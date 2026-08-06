import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from tools.build_canary_iso import (
    IsoBuildError,
    _sanitize_dump_xml,
    expected_shift_segments,
    load_config,
    tree_file_map,
    validate_directory_contract,
    validate_replacement_sector_budget,
    write_build_xml,
)
from tools.srwz.iso9660 import IsoMember


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
        self.assertEqual(
            expected_shift_segments(config),
            (("DATA/STAGE.BIN", 0),),
        )

    def test_explicit_shift_segments_are_validated(self):
        root = Path(__file__).resolve().parents[1]
        config = json.loads(
            (root / "config" / "iso" / "canary-build.json").read_text()
        )
        config["layout"]["shift_segments"] = [
            {"first_member": "A.BIN", "shift_sectors": 2},
            {"first_member": "B.BIN", "shift_sectors": 3},
        ]
        validate_directory_contract(config)
        self.assertEqual(
            expected_shift_segments(config),
            (("A.BIN", 2), ("B.BIN", 3)),
        )

    def test_shift_segments_must_be_monotonic(self):
        root = Path(__file__).resolve().parents[1]
        config = json.loads(
            (root / "config" / "iso" / "canary-build.json").read_text()
        )
        config["layout"]["shift_segments"] = [
            {"first_member": "A.BIN", "shift_sectors": 3},
            {"first_member": "B.BIN", "shift_sectors": 2},
        ]
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
            "replacements": [
                {"member": "DATA/VT1.BIN", "size": 2049}
            ],
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
            "replacements": [
                {"member": "DATA/VT1.BIN", "size": 2048}
            ],
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

    def test_evidence_manifests_must_stay_under_manifests(self):
        root = Path(__file__).resolve().parents[1]
        config = json.loads(
            (root / "config" / "iso" / "canary-build.json").read_text()
        )
        invalid = copy.deepcopy(config)
        invalid["component_validation_manifest"] = (
            "work/review/component-validation.json"
        )
        with self.assertRaisesRegex(
            IsoBuildError,
            "component validation manifest must be under manifests/",
        ):
            validate_directory_contract(invalid)

    def test_evidence_manifests_must_be_json(self):
        root = Path(__file__).resolve().parents[1]
        config = json.loads(
            (root / "config" / "iso" / "canary-build.json").read_text()
        )
        invalid = copy.deepcopy(config)
        invalid["runtime_evidence_manifest"] = "manifests/runtime.txt"
        with self.assertRaisesRegex(
            IsoBuildError,
            "runtime_evidence_manifest path must end in .json",
        ):
            validate_directory_contract(invalid)

    def test_repository_iso_config_loads_with_directory_contract(self):
        root = Path(__file__).resolve().parents[1]
        config = load_config(
            root / "config" / "iso" / "canary-build.json"
        )
        self.assertEqual(config["profile_id"], "canary-menu")

    def test_image_canary_config_has_isolated_profile_paths(self):
        root = Path(__file__).resolve().parents[1]
        config = load_config(
            root / "config" / "iso" / "image-canary-build.json"
        )
        self.assertEqual(config["profile_id"], "canary-image-vt1-title")
        self.assertEqual(config["layout"]["expected_shift_sectors"], 37)
        self.assertEqual(
            config["runtime_evidence_manifest"],
            "manifests/image-canary-validation.json",
        )
        self.assertEqual(
            config["output"]["path"],
            "build/iso/canary-image-vt1-title/srwz-image-canary.iso",
        )
        self.assertEqual(
            [item["member"] for item in config["replacements"]],
            ["SLPS_258.87", "DATA/VT1.BIN"],
        )

    def test_image_component_and_iso_configs_share_profile_and_hash(self):
        root = Path(__file__).resolve().parents[1]
        iso_config = json.loads(
            (
                root / "config" / "iso" / "image-canary-build.json"
            ).read_text()
        )
        component_config = json.loads(
            (
                root
                / "config"
                / "canary"
                / "tim2-vt1-title-index.json"
            ).read_text()
        )
        replacements = {
            item["member"]: item
            for item in iso_config["replacements"]
        }
        self.assertEqual(
            iso_config["profile_id"],
            component_config["profile_id"],
        )
        self.assertEqual(
            replacements["SLPS_258.87"]["source"],
            component_config["outputs"]["executable"],
        )
        self.assertEqual(
            replacements["SLPS_258.87"]["sha256"],
            component_config["expected_outputs"]["executable"]["sha256"],
        )
        self.assertEqual(
            replacements["SLPS_258.87"]["size"],
            component_config["expected_outputs"]["executable"]["size"],
        )
        self.assertEqual(
            replacements["DATA/VT1.BIN"]["source"],
            component_config["outputs"]["archive"],
        )
        self.assertEqual(
            replacements["DATA/VT1.BIN"]["sha256"],
            component_config["expected_outputs"]["archive"]["sha256"],
        )
        self.assertEqual(
            replacements["DATA/VT1.BIN"]["size"],
            component_config["expected_outputs"]["archive"]["size"],
        )

    def test_title_menu_chinese_configs_share_profile_and_hashes(self):
        root = Path(__file__).resolve().parents[1]
        iso_config = load_config(
            root / "config" / "iso" / "title-menu-zh-build.json"
        )
        component_config = json.loads(
            (
                root
                / "config"
                / "canary"
                / "tim2-vt1-title-zh.json"
            ).read_text()
        )
        self.assertEqual(iso_config["profile_id"], "title-menu-zh")
        self.assertEqual(
            iso_config["runtime_evidence_manifest"],
            "manifests/title-menu-zh-validation.json",
        )
        self.assertEqual(
            iso_config["layout"]["shift_segments"],
            [
                {
                    "first_member": "DATA/NISVDATA.BIN",
                    "shift_sectors": 0,
                },
            ],
        )
        self.assertEqual(
            iso_config["output"]["path"],
            "build/iso/title-menu-zh/srwz-title-menu-zh.iso",
        )
        self.assertEqual(
            iso_config["profile_id"],
            component_config["profile_id"],
        )
        replacements = {
            item["member"]: item
            for item in iso_config["replacements"]
        }
        for member, output_name in (
            ("SLPS_258.87", "executable"),
            ("DATA/VT1.BIN", "archive"),
        ):
            self.assertEqual(
                replacements[member]["source"],
                component_config["outputs"][output_name],
            )
            self.assertEqual(
                replacements[member]["size"],
                component_config["expected_outputs"][output_name]["size"],
            )
            self.assertEqual(
                replacements[member]["sha256"],
                component_config["expected_outputs"][output_name]["sha256"],
            )

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

    def test_complete_component_build_emits_isolated_fixture_inputs(self):
        root = Path(__file__).resolve().parents[1]
        component_config = json.loads(
            (
                root
                / "config"
                / "canary"
                / "complete-content.json"
            ).read_text()
        )
        self.assertEqual(
            component_config["isolated_profiles"],
            {
                "canary-summary": (
                    "config/build-profiles/canary-summary.json"
                ),
                "canary-story": (
                    "config/build-profiles/canary-story.json"
                ),
            },
        )
        expected = {
            "canary-summary": {
                "slps",
                "vt1",
                "mtv_pros",
            },
            "canary-story": {
                "slps",
                "vt1",
                "stage",
                "hb",
            },
        }
        self.assertEqual(
            {
                profile_id: set(outputs)
                for profile_id, outputs
                in component_config["isolated_outputs"].items()
            },
            expected,
        )
        for profile_id, output_names in expected.items():
            iso_config = load_config(
                root
                / "config"
                / "iso"
                / f"{profile_id}-build.json"
            )
            replacements = {
                item["source"]
                for item in iso_config["replacements"]
            }
            self.assertEqual(
                replacements,
                {
                    component_config["isolated_outputs"][profile_id][name]
                    for name in output_names
                },
            )

    def test_world_history_component_and_iso_configs_share_output_locks(self):
        root = Path(__file__).resolve().parents[1]
        iso_config = load_config(
            root
            / "config"
            / "iso"
            / "ui-p1-world-history-build.json"
        )
        component_config = json.loads(
            (
                root
                / "config"
                / "summary"
                / "world-history-component.json"
            ).read_text()
        )
        self.assertEqual(
            iso_config["profile_id"],
            "ui-p1-world-history",
        )
        self.assertEqual(
            iso_config["runtime_evidence_manifest"],
            "manifests/ui-p1-world-history-runtime-validation.json",
        )
        self.assertEqual(
            iso_config["output"]["path"],
            (
                "build/iso/ui-p1-world-history/"
                "srwz-ui-p1-world-history.iso"
            ),
        )
        replacements = {
            item["member"]: item
            for item in iso_config["replacements"]
        }
        for member, output_name, relative_path in (
            ("SLPS_258.87", "slps", "SLPS_258.87"),
            ("DATA/VT1.BIN", "vt1", "DATA/VT1.BIN"),
            ("DATA/MTV_PROS.BIN", "mtv_pros", "DATA/MTV_PROS.BIN"),
        ):
            self.assertEqual(
                replacements[member]["source"],
                (
                    f'{component_config["outputs"]["component_root"]}/'
                    f"{relative_path}"
                ),
            )
            self.assertEqual(
                {
                    "size": replacements[member]["size"],
                    "sha256": replacements[member]["sha256"],
                },
                component_config["expected_outputs"][output_name],
            )


if __name__ == "__main__":
    unittest.main()
