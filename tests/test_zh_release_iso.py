import hashlib
import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILD_CONFIG = PROJECT_ROOT / "config/iso/zh-release-full-story-build.json"
CHAIN_CONFIG = PROJECT_ROOT / "config/iso/zh-release-chain.json"
COMPONENT_MANIFEST = (
    PROJECT_ROOT / "manifests/full-story-components-validation.json"
)
ISO_REPORT = (
    PROJECT_ROOT / "build/iso/zh-release-full-story/iso-validation.json"
)
CONTENT_MANIFEST = (
    PROJECT_ROOT
    / "manifests/zh-release-full-story-iso-content-validation.json"
)
FONT_PROPOSAL = (
    PROJECT_ROOT / "work/writeback/zh-release-codebook-proposal.json"
)
STAGE_REPORT = (
    PROJECT_ROOT
    / "work/build/full-story-stage/components/component-validation.json"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


class ZhReleaseIsoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(BUILD_CONFIG.read_text(encoding="utf-8"))
        cls.chain = json.loads(CHAIN_CONFIG.read_text(encoding="utf-8"))
        cls.component = json.loads(
            COMPONENT_MANIFEST.read_text(encoding="utf-8")
        )
        cls.iso_report = json.loads(ISO_REPORT.read_text(encoding="utf-8"))
        cls.content = json.loads(
            CONTENT_MANIFEST.read_text(encoding="utf-8")
        )
        cls.proposal = json.loads(FONT_PROPOSAL.read_text(encoding="utf-8"))
        cls.stage = json.loads(STAGE_REPORT.read_text(encoding="utf-8"))

    def test_iso_replacements_are_bound_to_current_component_outputs(self):
        replacements = {
            item["member"]: {
                "path": item["source"],
                "size": item["size"],
                "sha256": item["sha256"],
            }
            for item in self.config["replacements"]
        }
        self.assertTrue(self.config["require_component_output_binding"])
        self.assertEqual(replacements, self.component["outputs"])
        self.assertEqual(
            self.config["component_required_status"],
            self.component["status"],
        )
        self.assertTrue(
            self.config["layout"][
                "preserve_original_member_sector_allocations"
            ]
        )
        self.assertTrue(
            all(
                segment["shift_sectors"] == 0
                for segment in self.config["layout"]["shift_segments"]
            )
        )

    def test_new_character_uses_a_default_width_global_assignment(self):
        assignments = {
            item["character"]: item for item in self.proposal["assignments"]
        }
        dai = assignments["岱"]
        self.assertEqual(dai["code"], "90BB")
        self.assertFalse(0x8140 <= int(dai["code"], 16) < 0x889F)
        self.assertEqual(
            self.stage["unaliased_conditional_localized_assignment_count"],
            self.proposal["surface_safe_aliases"][
                "unaliased_conditional_assignment_count"
            ],
        )
        self.assertEqual(
            self.component["story"]["minimum_compressed_chunk_headroom"],
            22,
        )

    def test_final_iso_hash_layout_and_single_candidate_are_locked(self):
        output = self.config["output"]
        iso_path = PROJECT_ROOT / output["path"]
        generated = sorted((PROJECT_ROOT / "build/iso").rglob("*.iso"))
        self.assertEqual(generated, [iso_path])
        self.assertEqual(iso_path.stat().st_size, output["expected_size"])
        self.assertEqual(sha256_file(iso_path), output["expected_sha256"])
        self.assertEqual(
            self.iso_report["output_iso"]["sha256"],
            output["expected_sha256"],
        )
        self.assertEqual(
            self.iso_report["layout"]["member_manifest_sha256"],
            output["expected_member_manifest_sha256"],
        )
        self.assertEqual(self.iso_report["layout"]["shifted_member_count"], 0)
        self.assertEqual(self.iso_report["layout"]["unchanged_member_count"], 59)
        self.assertTrue(
            self.iso_report["component_binding"][
                "all_replacements_match_component_outputs"
            ]
        )

    def test_final_iso_content_readback_is_complete(self):
        self.assertEqual(self.content["stage_count"], 154)
        self.assertEqual(self.content["translation_entry_count"], 91746)
        self.assertEqual(self.content["dialogue_count"], 82719)
        self.assertEqual(self.content["condition_count"], 558)
        self.assertEqual(self.content["speaker_count"], 8469)
        self.assertEqual(
            self.content["iso"]["sha256"],
            self.config["output"]["expected_sha256"],
        )
        self.assertTrue(all(self.content["checks"].values()))

    def test_battle_text_domain_is_explicitly_excluded_and_runtime_pending(self):
        step = self.chain["steps"][0]
        self.assertEqual(
            step["excluded_incomplete_domains"],
            ["BTL/SRVC.BIN", "BTL/SRVC.SEG"],
        )
        self.assertEqual(step["runtime_status"], "not_tested")
        self.assertFalse(step["promotion_eligible"])
        self.assertEqual(
            self.iso_report["runtime_acceptance"],
            "not tested by ISO builder",
        )


if __name__ == "__main__":
    unittest.main()
