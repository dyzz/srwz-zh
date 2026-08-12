import json
import unittest
from pathlib import Path

from tools import build_full_story_components, build_iso


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config/full-story-components.json"


class IncrementalComponentReuseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cls.manifest_path = (
            PROJECT_ROOT / cls.config["outputs"]["manifest"]
        )

    def test_incremental_plan_maps_one_fixed_field_only_to_slps(self):
        baseline_config = json.loads(json.dumps(self.config))
        current_config = json.loads(json.dumps(self.config))
        baseline_ui = json.loads(
            (PROJECT_ROOT / "corpus/zh/menu/remaining-ui.json").read_text(
                encoding="utf-8"
            )
        )
        current_ui = json.loads(json.dumps(baseline_ui))
        current_ui["slps_by_offset"]["0x3479E0"] = "钢狮子测试"
        current_ui["accepted_current_preimages_by_offset"]["0x3479E0"] = (
            "钢狮子"
        )
        current_config["remaining_ui"]["expected"][
            "accepted_current_preimage_count"
        ] += 1
        prior = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        remaining_labels = {
            "remaining_display_names",
            "remaining_ui_translations",
            "auto_demo_residual_names",
        }
        for label, lock in list(prior["inputs"].items()):
            if label == "config" or label in remaining_labels:
                continue
            path = (PROJECT_ROOT / lock["path"]).resolve()
            prior["inputs"][label] = build_full_story_components._file_lock(
                path,
                path.read_bytes(),
            )
        remaining_lock = prior["inputs"]["remaining_ui_translations"]
        changed_lock = dict(remaining_lock)
        changed_lock["sha256"] = "0" * 64
        for label in remaining_labels:
            prior["inputs"][label] = changed_lock
        changed, reasons = build_full_story_components._plan_incremental_members(
            baseline_config=baseline_config,
            current_config=current_config,
            baseline_remaining_ui=baseline_ui,
            current_remaining_ui=current_ui,
            prior_report=prior,
        )
        self.assertEqual(changed, {build_full_story_components.SLPS_MEMBER})
        self.assertIn("remaining-ui:slps_by_offset", reasons)

    def test_incremental_plan_maps_compdata_ui_to_compdata(self):
        baseline_ui = json.loads(
            (PROJECT_ROOT / "corpus/zh/menu/remaining-ui.json").read_text(
                encoding="utf-8"
            )
        )
        current_ui = json.loads(json.dumps(baseline_ui))
        first = next(iter(current_ui["compdata_direct_by_offset"]))
        current_ui["compdata_direct_by_offset"][first] += "测试"
        changed, _reasons = build_full_story_components._changed_remaining_ui_impacts(
            baseline_ui,
            current_ui,
        )
        self.assertEqual(changed, {build_full_story_components.COMPDATA_MEMBER})

    def test_every_manifest_input_has_an_incremental_dependency_rule(self):
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        special = {
            "config",
            "remaining_display_names",
            "remaining_ui_translations",
            "auto_demo_residual_names",
        }
        unknown = []
        for label in manifest["inputs"]:
            if label in special or label in build_full_story_components.INPUT_IMPACTS:
                continue
            if label.startswith("auto_demo_original_op") and (
                label.endswith("_bin") or label.endswith("_seg")
            ):
                continue
            unknown.append(label)
        self.assertEqual(unknown, [])

    def test_every_component_member_is_declared(self):
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(
            set(manifest["outputs"]),
            build_full_story_components.ALL_COMPONENT_MEMBERS,
        )

    def test_fixed_slps_executor_emits_only_slps_and_updates_inventory(self):
        current_ui = json.loads(
            (PROJECT_ROOT / "corpus/zh/menu/remaining-ui.json").read_text(
                encoding="utf-8"
            )
        )
        baseline_ui = json.loads(json.dumps(current_ui))
        baseline_ui["slps_by_offset"].pop("0x3479E0")
        baseline_ui["accepted_current_preimages_by_offset"].pop(
            "0x3479E0", None
        )
        expected_report = json.loads(
            self.manifest_path.read_text(encoding="utf-8")
        )
        prior = json.loads(json.dumps(expected_report))
        prior_slps = prior["remaining_ui"]["slps"]
        prior_slps["entry_count"] -= 1
        prior_slps["write_entry_count"] -= 1
        prior_slps["changed_byte_count"] -= 4
        payloads, report = (
            build_full_story_components._build_incremental_fixed_slps(
                config_path=CONFIG_PATH,
                config=self.config,
                output_root=(
                    PROJECT_ROOT
                    / self.config["outputs"]["component_root"]
                ),
                prior_report=prior,
                baseline_remaining_ui=baseline_ui,
                current_remaining_ui=current_ui,
            )
        )
        self.assertEqual(
            set(payloads), {build_full_story_components.SLPS_MEMBER}
        )
        self.assertEqual(
            report["remaining_ui"]["slps"]["entry_count"],
            expected_report["remaining_ui"]["slps"]["entry_count"],
        )
        self.assertEqual(
            report["remaining_ui"]["slps"]["write_entry_count"],
            expected_report["remaining_ui"]["slps"]["write_entry_count"],
        )
        self.assertEqual(report["outputs"], expected_report["outputs"])
        self.assertEqual(report["acceptance"], expected_report["acceptance"])

    def test_working_iso_lock_refresh_follows_component_manifest(self):
        current_config = json.loads(
            (
                PROJECT_ROOT / "config/iso/zh-release-current-build.json"
            ).read_text(encoding="utf-8")
        )
        slps = next(
            item
            for item in current_config["replacements"]
            if item["member"] == "SLPS_258.87"
        )
        slps["sha256"] = "0" * 64
        refreshed = build_iso.refresh_component_output_locks(current_config)
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(refreshed, len(current_config["replacements"]))
        self.assertEqual(
            slps["sha256"],
            manifest["outputs"]["SLPS_258.87"]["sha256"],
        )
        self.assertNotIn("expected_sha256", current_config["output"])
        self.assertNotIn(
            "expected_member_manifest_sha256",
            current_config["output"],
        )

    def test_release_iso_lock_refresh_is_refused(self):
        release_config = json.loads(
            (
                PROJECT_ROOT / "config/iso/zh-release-full-story-build.json"
            ).read_text(encoding="utf-8")
        )
        with self.assertRaisesRegex(
            build_iso.IsoBuildError,
            "refusing to refresh output locks in a release profile",
        ):
            build_iso.refresh_component_output_locks(release_config)


if __name__ == "__main__":
    unittest.main()
