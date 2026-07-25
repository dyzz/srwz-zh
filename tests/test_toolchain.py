import json
import unittest
from pathlib import Path

from tools.srwz.toolchain import (
    OFFICIAL_ARMIPS_REPOSITORY,
    load_armips_lock,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ToolchainContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lock = load_armips_lock(
            PROJECT_ROOT
            / "config"
            / "toolchain"
            / "armips.lock.json"
        )
        cls.patch_contract = json.loads(
            (
                PROJECT_ROOT
                / "config"
                / "patches"
                / "upstream-asm-audit.json"
            ).read_text(encoding="utf-8")
        )
        cls.manifest = json.loads(
            (
                PROJECT_ROOT
                / "manifests"
                / "toolchain-validation.json"
            ).read_text(encoding="utf-8")
        )

    def test_armips_lock_uses_only_official_mit_source(self):
        self.assertEqual(
            self.lock["repository"],
            OFFICIAL_ARMIPS_REPOSITORY,
        )
        self.assertEqual(self.lock["license"]["spdx"], "MIT")
        self.assertEqual(
            {version["id"] for version in self.lock["versions"]},
            {"reference_2023", "selected"},
        )
        for version in self.lock["versions"]:
            self.assertFalse(version["source_path"].endswith(".exe"))
            self.assertFalse(version["bootstrap_path"].endswith(".exe"))

    def test_two_clean_builds_are_pinned_and_identical(self):
        versions = self.manifest["armips"]["versions"]
        for version in self.lock["versions"]:
            observed = versions[version["id"]]
            self.assertEqual(observed["clean_build_count"], 2)
            self.assertEqual(observed["ctest_pass_count"], 2)
            self.assertTrue(observed["clean_builds_identical"])
            self.assertEqual(
                observed["binary_sha256"],
                version["expected_binary_sha256"],
            )

    def test_project_asm_outputs_match_both_versions(self):
        project = self.manifest["project_asm"]
        self.assertTrue(project["upstream_clean"])
        self.assertTrue(project["versions_identical_for_all_targets"])
        locked = {
            target["id"]: target
            for target in self.lock["project_asm_check"]["targets"]
        }
        for target_id, target in project["targets"].items():
            self.assertEqual(
                target["output_sha256"],
                locked[target_id]["output_sha256"],
            )
            self.assertEqual(
                target["input_sha256"],
                locked[target_id]["input_sha256"],
            )

    def test_patch_contract_locks_complete_final_diffs(self):
        targets = {
            target["id"]: target
            for target in self.patch_contract["targets"]
        }
        observed = self.manifest["project_asm"]["targets"]
        for target_id, target in targets.items():
            expected = target["expected_diff"]
            self.assertEqual(
                set(expected),
                {
                    "diff_count",
                    "range_count",
                    "first_offset",
                    "last_offset",
                    "offsets_sha256",
                    "ranges_sha256",
                    "before_values_sha256",
                    "after_values_sha256",
                },
            )
            self.assertEqual(
                expected["diff_count"],
                observed[target_id]["diff_count"],
            )
            self.assertEqual(
                expected["before_values_sha256"],
                observed[target_id]["before_values_sha256"],
            )
            self.assertEqual(
                expected["after_values_sha256"],
                observed[target_id]["after_values_sha256"],
            )
            self.assertEqual(
                len(target["owners"]),
                observed[target_id]["owner_count"],
            )
            self.assertEqual(
                len(target["allowed_overlaps"]),
                observed[target_id]["explicit_overlap_count"],
            )

    def test_all_completion_gates_passed(self):
        self.assertEqual(
            set(self.manifest["completion_gates"].values()),
            {True},
        )


if __name__ == "__main__":
    unittest.main()
