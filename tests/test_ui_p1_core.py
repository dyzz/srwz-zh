import hashlib
import json
import unittest
from pathlib import Path

from tools.srwz.iso_config import load_config
from tools.srwz.ui_integration import (
    UiIntegrationError,
    _apply_three_way_menu_patch,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config/ui-integration/p1-core.json"
MANIFEST_PATH = PROJECT_ROOT / "manifests/ui-p1-core-validation.json"
RUNTIME_MANIFEST_PATH = (
    PROJECT_ROOT / "manifests/ui-p1-core-runtime-validation.json"
)
ISO_CONFIG_PATH = PROJECT_ROOT / "config/iso/ui-p1-core-build.json"
COMPONENT_ROOT = PROJECT_ROOT / "work/build/ui-p1-core/components"


def sha256_path(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


class UiP1CoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cls.manifest = json.loads(
            MANIFEST_PATH.read_text(encoding="utf-8")
        )
        cls.runtime = json.loads(
            RUNTIME_MANIFEST_PATH.read_text(encoding="utf-8")
        )
        cls.iso_config = load_config(ISO_CONFIG_PATH)

    def test_three_way_patch_rejects_overlapping_owners(self):
        with self.assertRaisesRegex(
            UiIntegrationError,
            "ratchet drift|overlaps",
        ):
            _apply_three_way_menu_patch(
                b"aaaa",
                b"abaa",
                b"acaa",
                {
                    "mode": "three-way-byte-patch",
                    "expected_changed_byte_count": 1,
                    "expected_changed_range_count": 1,
                    "expected_base_overlap_count": 0,
                },
            )

    def test_three_way_patch_preserves_disjoint_base_changes(self):
        output, report = _apply_three_way_menu_patch(
            b"aaaa",
            b"abaa",
            b"aaca",
            {
                "mode": "three-way-byte-patch",
                "expected_changed_byte_count": 1,
                "expected_changed_range_count": 1,
                "expected_base_overlap_count": 0,
            },
        )
        self.assertEqual(output, b"abca")
        self.assertEqual(report["overlap_count"], 0)
        self.assertTrue(report["menu_bytes_exact"])
        self.assertTrue(report["world_bytes_outside_menu_exact"])

    def test_all_dependency_hashes_are_current(self):
        for component in self.config["components"].values():
            for key in ("config", "manifest"):
                reference = component.get(key)
                if reference is None:
                    continue
                path = PROJECT_ROOT / reference["path"]
                self.assertEqual(
                    sha256_path(path),
                    reference["sha256"],
                )

    def test_integrated_component_ratchet_and_ownership(self):
        self.assertEqual(
            self.manifest["status"],
            "integrated_component_validated_iso_runtime_pending",
        )
        self.assertTrue(self.manifest["ratchet"]["passed"])
        self.assertEqual(
            self.manifest["ratchet"]["actual"],
            self.config["ratchet"],
        )
        menu = self.manifest["composition"]["slps_menu"]
        self.assertEqual(menu["overlap_count"], 0)
        self.assertEqual(menu["menu_diff"]["diff_count"], 2659)
        self.assertEqual(menu["menu_diff"]["range_count"], 496)
        title = self.manifest["composition"]["title_menu"]
        self.assertEqual(title["chunk_index"], 6)
        self.assertEqual(title["record_index"], 1)
        self.assertEqual(title["changed_pixel_count"], 12514)
        self.assertEqual(title["unchanged_chunk_count"], 13)
        self.assertTrue(title["final_record_exact"])
        history = self.manifest["composition"]["mtv_pros"]
        self.assertEqual(history["entry_count"], 28)
        self.assertTrue(history["all_texts_exact"])
        self.assertEqual(history["unknown_code_count"], 0)

    def test_component_files_match_pinned_outputs(self):
        paths = {
            "slps": COMPONENT_ROOT / "SLPS_258.87",
            "vt1": COMPONENT_ROOT / "DATA/VT1.BIN",
            "mtv_pros": COMPONENT_ROOT / "DATA/MTV_PROS.BIN",
            "compdata": COMPONENT_ROOT / "DATA/COMPDATA.BN",
        }
        for name, path in paths.items():
            self.assertEqual(
                {
                    "size": path.stat().st_size,
                    "sha256": sha256_path(path),
                },
                self.config["expected_outputs"][name],
            )

    def test_iso_config_uses_only_integrated_outputs(self):
        self.assertEqual(self.iso_config["profile_id"], "ui-p1-core")
        replacements = {
            item["member"]: item
            for item in self.iso_config["replacements"]
        }
        mapping = {
            "SLPS_258.87": ("slps", "SLPS_258.87"),
            "DATA/COMPDATA.BN": ("compdata", "DATA/COMPDATA.BN"),
            "DATA/MTV_PROS.BIN": ("mtv_pros", "DATA/MTV_PROS.BIN"),
            "DATA/VT1.BIN": ("vt1", "DATA/VT1.BIN"),
        }
        self.assertEqual(set(replacements), set(mapping))
        for member, (output_name, relative_path) in mapping.items():
            replacement = replacements[member]
            self.assertEqual(
                replacement["source"],
                (
                    f'{self.config["outputs"]["component_root"]}/'
                    f"{relative_path}"
                ),
            )
            self.assertEqual(
                {
                    "size": replacement["size"],
                    "sha256": replacement["sha256"],
                },
                self.config["expected_outputs"][output_name],
            )
        self.assertEqual(
            self.iso_config["layout"]["shift_segments"],
            [
                {
                    "first_member": "DATA/NISVDATA.BIN",
                    "shift_sectors": 6,
                },
                {
                    "first_member": "DATA/STAGE.BIN",
                    "shift_sectors": 41,
                },
            ],
        )

    def test_static_iso_is_bound_without_runtime_overclaim(self):
        self.assertEqual(
            self.runtime["status"],
            "static_integrated_iso_validated_runtime_pending",
        )
        self.assertEqual(self.runtime["iso_build"]["member_count"], 66)
        self.assertEqual(
            self.runtime["iso_build"]["unchanged_member_count"],
            62,
        )
        self.assertEqual(
            self.runtime["iso_build"]["pcsx2_v263_image_type"],
            "DVD",
        )
        self.assertTrue(all(self.runtime["static_acceptance"].values()))
        self.assertEqual(self.runtime["runtime"]["status"], "not_tested")
        self.assertEqual(
            self.runtime["runtime"]["required_iso_sha256"],
            self.runtime["iso_build"]["output"]["sha256"],
        )


if __name__ == "__main__":
    unittest.main()
