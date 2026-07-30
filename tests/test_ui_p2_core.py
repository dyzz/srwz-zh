import hashlib
import json
import unittest
from pathlib import Path

from tools.srwz.iso_config import load_config


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = (
    PROJECT_ROOT
    / "config/ui-integration/p2-researched-display-names.json"
)
MANIFEST_PATH = PROJECT_ROOT / "manifests/ui-p2-core-validation.json"
WORLD_MANIFEST_PATH = (
    PROJECT_ROOT / "manifests/ui-p2-world-history-validation.json"
)
RUNTIME_MANIFEST_PATH = (
    PROJECT_ROOT / "manifests/ui-p2-core-runtime-validation.json"
)
ISO_CONFIG_PATH = PROJECT_ROOT / "config/iso/ui-p2-core-build.json"
COMPONENT_ROOT = PROJECT_ROOT / "work/build/ui-p2-core/components"


def sha256_path(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


class UiP2CoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cls.manifest = json.loads(
            MANIFEST_PATH.read_text(encoding="utf-8")
        )
        cls.world = json.loads(
            WORLD_MANIFEST_PATH.read_text(encoding="utf-8")
        )
        cls.runtime = json.loads(
            RUNTIME_MANIFEST_PATH.read_text(encoding="utf-8")
        )
        cls.iso_config = load_config(ISO_CONFIG_PATH)

    def test_all_dependency_hashes_are_current(self):
        for component in self.config["components"].values():
            for key in ("config", "manifest"):
                reference = component.get(key)
                if reference is None:
                    continue
                self.assertEqual(
                    sha256_path(PROJECT_ROOT / reference["path"]),
                    reference["sha256"],
                )

    def test_integrated_component_owns_all_selected_names(self):
        self.assertEqual(
            self.manifest["status"],
            "integrated_component_validated_iso_runtime_pending",
        )
        self.assertTrue(self.manifest["ratchet"]["passed"])
        actual = self.manifest["ratchet"]["actual"]
        self.assertEqual(actual, self.config["ratchet"])
        self.assertEqual(actual["p0_display_name_entry_count"], 1307)
        self.assertEqual(actual["world_history_entry_count"], 28)
        self.assertEqual(actual["p0_slps_covered_entry_count"], 418)
        self.assertEqual(actual["slps_component_overlap_count"], 0)
        self.assertEqual(
            self.manifest["composition"]["compdata"]["entry_count"],
            1307,
        )

    def test_world_history_inherits_the_exact_p2_font(self):
        self.assertTrue(
            self.world["vt1_component"][
                "p2_display_name_font_component_exact"
            ]
        )
        self.assertTrue(
            self.world["acceptance"][
                "p2_display_name_font_component_exact"
            ]
        )
        self.assertEqual(
            self.world["selection"]["translation_entry_count"],
            28,
        )
        self.assertEqual(self.world["runtime"]["status"], "not_tested")

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

    def test_iso_profile_binds_only_integrated_outputs(self):
        self.assertEqual(self.iso_config["profile_id"], "ui-p2-core")
        replacements = {
            item["member"]: item
            for item in self.iso_config["replacements"]
        }
        self.assertEqual(
            set(replacements),
            {
                "SLPS_258.87",
                "DATA/COMPDATA.BN",
                "DATA/MTV_PROS.BIN",
                "DATA/VT1.BIN",
            },
        )
        self.assertEqual(
            self.iso_config["layout"]["shift_segments"],
            [
                {
                    "first_member": "DATA/NISVDATA.BIN",
                    "shift_sectors": 0,
                },
            ],
        )

    def test_static_iso_is_pinned_without_runtime_overclaim(self):
        self.assertEqual(
            self.runtime["status"],
            "integrated_iso_boot_smoke_passed_visual_pending",
        )
        self.assertEqual(self.runtime["iso_build"]["member_count"], 66)
        self.assertEqual(
            self.runtime["iso_build"]["unchanged_member_count"],
            62,
        )
        self.assertEqual(
            self.runtime["iso_build"]["output"]["sha256"],
            "be95af17bcfe62ff6b0dfc5f7d9665118440c9adaa8061c071881471f76ef811",
        )
        self.assertTrue(all(self.runtime["static_acceptance"].values()))
        self.assertEqual(
            self.runtime["runtime"]["status"],
            "boot_smoke_passed_visual_not_tested",
        )
        self.assertEqual(
            self.runtime["runtime"]["tlb_miss_count"],
            0,
        )


if __name__ == "__main__":
    unittest.main()
