import hashlib
import struct
import unittest

from tools.srwz.patch_audit import (
    PatchAuditError,
    audit_binary_patch,
    changed_offsets,
    sha256_bytes,
    summarize_diff,
)


def _offset_digest(offsets):
    return hashlib.sha256(
        b"".join(struct.pack("<I", offset) for offset in offsets)
    ).hexdigest()


def _expected_diff(before, after):
    return summarize_diff(before, after).to_mapping()


class PatchAuditTests(unittest.TestCase):
    def setUp(self):
        self.before = b"abcdefgh"
        self.owner_a = b"abXYefgh"
        self.owner_b = b"abcZWfgh"
        self.after = b"abXZWfgh"
        self.target = {
            "input": {
                "size": len(self.before),
                "sha256": sha256_bytes(self.before),
            },
            "output": {
                "size": len(self.after),
                "sha256": sha256_bytes(self.after),
            },
            "expected_diff": _expected_diff(
                self.before,
                self.after,
            ),
            "allowed_ranges": [
                {"start": 2, "end": 4, "owner": "a"},
                {"start": 3, "end": 5, "owner": "b"},
            ],
            "owners": {
                "a": {
                    "output_sha256": sha256_bytes(self.owner_a),
                    "diff": _expected_diff(
                        self.before,
                        self.owner_a,
                    ),
                },
                "b": {
                    "output_sha256": sha256_bytes(self.owner_b),
                    "diff": _expected_diff(
                        self.before,
                        self.owner_b,
                    ),
                },
            },
            "allowed_overlaps": [
                {
                    "owners": ["a", "b"],
                    "final_owner": "b",
                    "count": 1,
                    "offsets_sha256": _offset_digest((3,)),
                }
            ],
        }

    def test_audits_exact_diff_owners_and_explicit_overlap(self):
        report = audit_binary_patch(
            self.before,
            self.after,
            self.target,
            owner_outputs={
                "a": self.owner_a,
                "b": self.owner_b,
            },
        )
        self.assertEqual(report["diff"]["diff_count"], 3)
        self.assertEqual(report["owner_count"], 2)
        self.assertEqual(report["overlaps"][0]["count"], 1)

    def test_rejects_unknown_input(self):
        with self.assertRaisesRegex(PatchAuditError, "input SHA-256"):
            audit_binary_patch(
                b"bbcdefgh",
                self.after,
                self.target,
                owner_outputs={
                    "a": self.owner_a,
                    "b": self.owner_b,
                },
            )

    def test_rejects_file_expansion(self):
        target = dict(self.target)
        expanded = self.after + b"!"
        target["output"] = {
            "size": len(expanded),
            "sha256": sha256_bytes(expanded),
        }
        with self.assertRaisesRegex(PatchAuditError, "changes file size"):
            audit_binary_patch(
                self.before,
                expanded,
                target,
                owner_outputs={
                    "a": self.owner_a,
                    "b": self.owner_b,
                },
            )

    def test_rejects_write_outside_allowed_ranges(self):
        after = b"abXZWfg!"
        target = dict(self.target)
        target["output"] = {
            "size": len(after),
            "sha256": sha256_bytes(after),
        }
        target["expected_diff"] = _expected_diff(self.before, after)
        with self.assertRaisesRegex(PatchAuditError, "outside allowed"):
            audit_binary_patch(
                self.before,
                after,
                target,
                owner_outputs={
                    "a": self.owner_a,
                    "b": self.owner_b,
                },
            )

    def test_rejects_unlisted_implicit_overlap(self):
        target = dict(self.target)
        target["allowed_overlaps"] = []
        with self.assertRaisesRegex(PatchAuditError, "implicit overlap"):
            audit_binary_patch(
                self.before,
                self.after,
                target,
                owner_outputs={
                    "a": self.owner_a,
                    "b": self.owner_b,
                },
            )

    def test_rejects_owner_write_missing_from_final_diff(self):
        owner_b = b"abcZWfgh"
        after = b"abXZefgh"
        target = dict(self.target)
        target["output"] = {
            "size": len(after),
            "sha256": sha256_bytes(after),
        }
        target["expected_diff"] = _expected_diff(self.before, after)
        target["owners"] = dict(self.target["owners"])
        target["owners"]["b"] = dict(self.target["owners"]["b"])
        target["owners"]["b"]["output_sha256"] = sha256_bytes(owner_b)
        with self.assertRaisesRegex(PatchAuditError, "owner diff union"):
            audit_binary_patch(
                self.before,
                after,
                target,
                owner_outputs={
                    "a": self.owner_a,
                    "b": owner_b,
                },
            )

    def test_rejects_unexpected_final_diff_set(self):
        after = b"abXZYfgh"
        target = dict(self.target)
        target["output"] = {
            "size": len(after),
            "sha256": sha256_bytes(after),
        }
        with self.assertRaisesRegex(
            PatchAuditError,
            "expected_diff.after_values_sha256",
        ):
            audit_binary_patch(
                self.before,
                after,
                target,
                owner_outputs={
                    "a": self.owner_a,
                    "b": self.owner_b,
                },
            )

    def test_changed_offsets_rejects_size_mismatch(self):
        with self.assertRaisesRegex(PatchAuditError, "changes file size"):
            changed_offsets(b"a", b"ab")


if __name__ == "__main__":
    unittest.main()
