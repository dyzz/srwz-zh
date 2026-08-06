import copy
import json
import tempfile
import unittest
from pathlib import Path

from tools.srwz.iso9660 import SECTOR_SIZE, member_map, scan_iso9660
from tools.srwz.patch_audit import changed_offsets
from tools.srwz.ui_atlas_suite import (
    UiAtlasSuiteError,
    build_ui_atlas_suite,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
CONFIG_PATH = PROJECT_ROOT / "config/assets/ui-atlas-suite-zh.json"
MANIFEST_PATH = PROJECT_ROOT / "manifests/ui-atlas-suite-zh-validation.json"
ARCHIVE_PATH = (
    PROJECT_ROOT
    / "work/build/ui-atlas-suite-zh/components/KURODATA/KVMDATA.BIN"
)


class UiAtlasSuiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def _mutated_config(self, mutation):
        document = copy.deepcopy(self.config)
        mutation(document)
        temporary = tempfile.TemporaryDirectory(dir=WORK_ROOT)
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "suite.json"
        path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    def test_component_rebuild_and_manifest_are_exact(self):
        archive, report = build_ui_atlas_suite(PROJECT_ROOT, CONFIG_PATH)
        self.assertEqual(report, self.manifest)
        self.assertEqual(archive, ARCHIVE_PATH.read_bytes())
        self.assertEqual(
            report["outputs"]["archive"]["sha256"],
            "0aaf2564df92fff1f9a6016d8fd5f67d05981022c3c28ac5a5c60b826386544c",
        )

    def test_five_component_byte_owners_are_disjoint_and_exact(self):
        iso_path = PROJECT_ROOT / self.config["source"]["iso"]["path"]
        image = scan_iso9660(iso_path)
        member = member_map(image)[self.config["source"]["member"]["member"]]
        with iso_path.open("rb") as source:
            source.seek(member.extent_lba * SECTOR_SIZE)
            base = source.read(member.size)
        suite = ARCHIVE_PATH.read_bytes()
        owned = set()
        for component in self.config["components"]:
            path = PROJECT_ROOT / component["archive"]["path"]
            payload = path.read_bytes()
            offsets = set(changed_offsets(base, payload))
            self.assertTrue(offsets)
            self.assertFalse(owned & offsets)
            self.assertTrue(all(suite[offset] == payload[offset] for offset in offsets))
            owned.update(offsets)
        self.assertEqual(len(owned), 5623)
        self.assertTrue(
            all(
                suite[offset] == base[offset]
                for offset in range(len(base))
                if offset not in owned
            )
        )

    def test_runtime_boundary_and_content_policy_are_explicit(self):
        self.assertEqual(
            self.manifest["status"],
            "static_combined_atlas_component_validated_runtime_mapping_pending",
        )
        self.assertEqual(self.manifest["runtime"]["status"], "not_tested")
        self.assertTrue(
            self.manifest["runtime"]["isolated_mapping_profiles_remain_required"]
        )
        self.assertEqual(
            self.manifest["composition"]["chunk_indices"],
            [2, 4, 5, 6, 7],
        )
        self.assertEqual(
            self.manifest["composition"]["ownership_overlap_count"],
            0,
        )
        self.assertTrue(all(self.manifest["acceptance"].values()))

    def test_manifest_contains_no_translation_payload(self):
        def visit(value):
            if isinstance(value, dict):
                self.assertNotIn("source_text", value)
                self.assertNotIn("translation", value)
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(self.manifest)

    def test_duplicate_component_is_rejected(self):
        path = self._mutated_config(
            lambda document: document["components"].append(
                copy.deepcopy(document["components"][0])
            )
        )
        with self.assertRaisesRegex(
            UiAtlasSuiteError,
            "profile or chunk is duplicated",
        ):
            build_ui_atlas_suite(
                PROJECT_ROOT,
                path,
                enforce_expected_output=False,
            )

    def test_component_manifest_hash_drift_is_rejected(self):
        path = self._mutated_config(
            lambda document: document["components"][0]["manifest"].update(
                {"sha256": "0" * 64}
            )
        )
        with self.assertRaisesRegex(
            UiAtlasSuiteError,
            "manifest size or SHA-256 drift",
        ):
            build_ui_atlas_suite(
                PROJECT_ROOT,
                path,
                enforce_expected_output=False,
            )


if __name__ == "__main__":
    unittest.main()
