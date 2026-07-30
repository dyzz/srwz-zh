import copy
import json
import tempfile
import unittest
from pathlib import Path

from tools.srwz.ui_database_selection import (
    UiDatabaseSelectionError,
    audit_ui_database_selection,
    build_database_selection_manifest,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config/ui-database-selection.json"
MANIFEST_PATH = (
    PROJECT_ROOT / "manifests/ui-database-fixed-core-selection.json"
)


class UiDatabaseSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cls.report = audit_ui_database_selection(
            PROJECT_ROOT,
            CONFIG_PATH,
        )
        cls.manifest = json.loads(
            MANIFEST_PATH.read_text(encoding="utf-8")
        )

    def _audit_mutation(self, mutate):
        document = copy.deepcopy(self.config)
        mutate(document)
        with tempfile.TemporaryDirectory(
            dir=PROJECT_ROOT / "work"
        ) as temporary:
            path = Path(temporary) / "selection.json"
            path.write_text(
                json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            return audit_ui_database_selection(PROJECT_ROOT, path)

    def test_manifest_is_reproducible_from_locked_inputs(self):
        self.assertEqual(
            build_database_selection_manifest(self.report),
            self.manifest,
        )
        self.assertEqual(
            self.manifest["status"],
            "static_database_fixed_subset_selected_font_extension_required",
        )

    def test_four_families_select_402_and_defer_848(self):
        selection = self.manifest["selection"]
        self.assertEqual(selection["selected_entry_count"], 402)
        self.assertEqual(selection["selected_slps_entry_count"], 232)
        self.assertEqual(selection["selected_compdata_entry_count"], 170)
        self.assertEqual(selection["deferred_entry_count"], 848)
        self.assertEqual(
            {
                family["runtime_scene_id"]: family["entry_count"]
                for family in selection["families"]
            },
            {
                "database/pilot-skills-core": 88,
                "database/unit-special-abilities-core": 155,
                "database/spirit-commands-core": 144,
                "database/leadership-effects-core": 15,
            },
        )

    def test_font_demand_and_fixed_spans_are_exact(self):
        demand = self.manifest["font_demand"]
        self.assertEqual(
            demand["missing_renderer_characters"],
            "咫垫挡斩框歼药赋赖镜闪－",
        )
        self.assertEqual(demand["missing_renderer_character_count"], 12)
        self.assertEqual(demand["original_font_han_count"], 14)
        fixed = self.manifest["fixed_span_readiness"]
        self.assertTrue(fixed["all_selected_entries_covered"])
        self.assertEqual(
            fixed["members"]["slps"]["selection"][
                "fixed_covered_entry_count"
            ],
            232,
        )
        self.assertEqual(
            fixed["members"]["compdata"]["selection"][
                "fixed_covered_entry_count"
            ],
            170,
        )
        self.assertEqual(
            sum(
                member["selection"]["excluded_entry_count"]
                for member in fixed["members"].values()
            ),
            0,
        )

    def test_family_count_drift_fails_closed(self):
        with self.assertRaisesRegex(
            UiDatabaseSelectionError,
            "database family count drift",
        ):
            self._audit_mutation(
                lambda document: document["families"][0].update(
                    {"expected_entry_count": 89}
                )
            )

    def test_protected_exclusions_cannot_disappear(self):
        with self.assertRaisesRegex(
            UiDatabaseSelectionError,
            "protected exclusions",
        ):
            self._audit_mutation(
                lambda document: document.update(
                    {"protected_exclusions": []}
                )
            )


if __name__ == "__main__":
    unittest.main()
