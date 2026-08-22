import hashlib
import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = (
    PROJECT_ROOT / "config/encoding/release-base-ui-mapping-snapshot.json"
)


class ReleaseBaseUiMappingSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))

    def test_historical_mapping_ratchet_is_exact(self):
        assignments = self.snapshot["assignments"]
        rows = sorted(
            (item["character"], item["code"], item["glyph_index"])
            for item in assignments
        )
        digest = hashlib.sha256(
            json.dumps(
                rows,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(len(assignments), 1803)
        self.assertEqual(self.snapshot["assignment_count"], 1803)
        self.assertEqual(
            digest,
            "8fc2647a77d4206efd5df3a8ac6d1e17266fbce8e3a3ef7d3a8ac7b736856c27",
        )
        self.assertEqual(self.snapshot["mapping_sha256"], digest)

    def test_binary_delta_authority_is_explicit(self):
        self.assertEqual(self.snapshot["changed_glyph_count"], 1802)
        self.assertEqual(self.snapshot["unchanged_selected_characters"], [" "])
        self.assertEqual(
            self.snapshot["selection_authority"],
            "original_vs_release_base_ui_decoded_glyph_delta_plus_locked_unchanged",
        )
        self.assertTrue(all(self.snapshot["acceptance"].values()))


if __name__ == "__main__":
    unittest.main()
