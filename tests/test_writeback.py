import unittest

from tools.srwz.writeback import (
    AllocationPool,
    PatchOperation,
    PatchPlan,
    WritebackError,
    fit_fixed_allocation,
    rebuild_aligned_archive,
    replace_archive_chunk_with_preceding_zero_slack,
    sha256_bytes,
)


class WritebackContractTests(unittest.TestCase):
    def test_patch_plan_verifies_preimage_and_applies(self):
        source = b"abcdef"
        plan = PatchPlan(
            source_name="fixture.bin",
            source_size=len(source),
            source_sha256=sha256_bytes(source),
            operations=(
                PatchOperation(
                    owner="menu/test",
                    offset=2,
                    before=b"cd",
                    after=b"XY",
                ),
            ),
        )
        self.assertEqual(plan.apply(source), b"abXYef")

    def test_patch_plan_rejects_overlapping_owners(self):
        source = b"abcdef"
        with self.assertRaisesRegex(WritebackError, "overlapping owners"):
            PatchPlan(
                source_name="fixture.bin",
                source_size=len(source),
                source_sha256=sha256_bytes(source),
                operations=(
                    PatchOperation("one", 1, b"bc", b"12"),
                    PatchOperation("two", 2, b"cd", b"34"),
                ),
            )

    def test_patch_plan_rejects_wrong_source_hash(self):
        source = b"abcdef"
        plan = PatchPlan(
            "fixture.bin",
            len(source),
            "0" * 64,
            (),
        )
        with self.assertRaisesRegex(WritebackError, "SHA-256 mismatch"):
            plan.verify_source(source)

    def test_patch_plan_rejects_wrong_preimage(self):
        source = b"abcdef"
        plan = PatchPlan(
            "fixture.bin",
            len(source),
            sha256_bytes(source),
            (PatchOperation("owner", 1, b"XX", b"12"),),
        )
        with self.assertRaisesRegex(WritebackError, "preimage mismatch"):
            plan.verify_source(source)

    def test_pool_allocates_with_alignment_and_fails_closed(self):
        pool = AllocationPool("menu", 3, 16)
        self.assertEqual(pool.allocate(4, alignment=4), 4)
        self.assertEqual(pool.remaining, 8)
        with self.assertRaisesRegex(WritebackError, "pool overflow"):
            pool.allocate(9)

    def test_fixed_allocation_never_truncates(self):
        self.assertEqual(
            fit_fixed_allocation(b"abc", 6),
            b"abc\x00\x00\x00",
        )
        with self.assertRaisesRegex(WritebackError, "overflow"):
            fit_fixed_allocation(b"abcdef", 6)

    def test_rebuild_archive_returns_terminal_offset(self):
        data, offsets = rebuild_aligned_archive((b"abc", b"12345"))
        self.assertEqual(offsets, (0, 16, 32))
        self.assertEqual(len(data), 32)
        self.assertEqual(data[:3], b"abc")
        self.assertEqual(data[16:21], b"12345")

    def test_archive_chunk_borrows_only_preceding_zero_slack(self):
        source = b"A" * 16 + bytes(16) + b"B" * 16
        rebuilt, offsets, padding, borrowed = (
            replace_archive_chunk_with_preceding_zero_slack(
                source,
                (0, 32, 48),
                chunk_index=1,
                replacement=b"C" * 24,
            )
        )
        self.assertEqual(len(rebuilt), len(source))
        self.assertEqual(offsets, (0, 16, 48))
        self.assertEqual(rebuilt[:16], b"A" * 16)
        self.assertEqual(rebuilt[16:40], b"C" * 24)
        self.assertEqual(rebuilt[40:], bytes(8))
        self.assertEqual(padding, 8)
        self.assertEqual(borrowed, 16)

    def test_archive_chunk_rejects_nonzero_borrowed_preimage(self):
        source = b"A" * 32 + b"B" * 16
        with self.assertRaisesRegex(
            WritebackError,
            "slack contains nonzero",
        ):
            replace_archive_chunk_with_preceding_zero_slack(
                source,
                (0, 32, 48),
                chunk_index=1,
                replacement=b"C" * 24,
            )


if __name__ == "__main__":
    unittest.main()
