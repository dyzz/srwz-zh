import json
import unittest
from pathlib import Path

from tools.srwz.ui_iso_incremental import (
    audit_ui_iso_incremental_chain,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config/iso/ui-incremental-chain.json"
MANIFEST_PATH = (
    PROJECT_ROOT / "manifests/ui-iso-incremental-validation.json"
)


class UiIsoIncrementalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        chain = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        missing_isos = [
            step["iso_path"]
            for step in chain["steps"]
            if not (PROJECT_ROOT / step["iso_path"]).is_file()
        ]
        if missing_isos:
            raise unittest.SkipTest(
                "historical multi-ISO chain is not retained under the "
                "single-candidate policy"
            )
        cls.report = audit_ui_iso_incremental_chain(
            PROJECT_ROOT,
            CONFIG_PATH,
        )
        cls.manifest = json.loads(
            MANIFEST_PATH.read_text(encoding="utf-8")
        )

    def test_manifest_is_reproducible(self):
        self.assertEqual(self.report, self.manifest)

    def test_chain_is_split_into_single_member_ui_deltas(self):
        self.assertEqual(self.report["chain"]["step_count"], 6)
        self.assertEqual(
            [
                step["delta_from_previous"]
                for step in self.report["steps"][1:]
            ],
            [
                ["KURODATA/KVMDATA.BIN"],
                ["DATA/VT1.BIN"],
                ["SLPS_258.87"],
                ["DATA/MTV_PROS.BIN"],
                ["DATA/COMPDATA.BN"],
            ],
        )

    def test_noncompdata_candidate_is_promoted(self):
        self.assertEqual(
            self.report["promoted_candidate"]["step_id"],
            "first-five-noncompdata-ui",
        )
        self.assertEqual(
            self.report["promoted_candidate"]["iso_sha256"],
            (
                "85ba645d980d84861f233a11c93b1f0cb3742a8a0583cec4"
                "1d9e70263851ec39"
            ),
        )

    def test_compdata_is_the_only_blocked_delta(self):
        self.assertEqual(
            self.report["blocked_candidate"]["delta_from_promoted"],
            ["DATA/COMPDATA.BN"],
        )
        self.assertIn(
            "TLB",
            self.report["blocked_candidate"]["reason"],
        )
        self.assertEqual(
            [
                step["promotion_eligible"]
                for step in self.report["steps"]
            ],
            [True, True, True, True, True, False],
        )

    def test_all_boot_receipts_recognized_dvd_and_elf(self):
        self.assertTrue(
            all(
                step["boot_smoke"]["checks"]["dvd_recognized"]
                and step["boot_smoke"]["checks"]["elf_executing"]
                for step in self.report["steps"]
            )
        )


if __name__ == "__main__":
    unittest.main()
