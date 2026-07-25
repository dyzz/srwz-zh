import unittest
from pathlib import Path

from tools.srwz.archive import (
    ArchiveLayoutError,
    OffsetLayout,
    load_offset_layout,
    slice_archive,
)


class OffsetLayoutTests(unittest.TestCase):
    def test_repository_stage_layout(self):
        project_root = Path(__file__).resolve().parents[1]
        layout = load_offset_layout(project_root / "config" / "stage-offsets.json")
        self.assertEqual(layout.chunk_count, 205)
        self.assertEqual(layout.offsets[-1], 3910128)

    def test_slices_archive_at_strict_offsets(self):
        layout = OffsetLayout(
            archive_path="DATA/TEST.BIN",
            offsets=(0, 2, 5, 8),
            expected_size=8,
        )

        self.assertEqual(
            list(slice_archive(b"abcdefgh", layout)),
            [b"ab", b"cde", b"fgh"],
        )

    def test_rejects_duplicate_offsets(self):
        layout = OffsetLayout(
            archive_path="DATA/TEST.BIN",
            offsets=(0, 2, 2, 8),
            expected_size=8,
        )

        with self.assertRaisesRegex(ArchiveLayoutError, "strictly increasing"):
            layout.validate()

    def test_rejects_wrong_archive_size(self):
        layout = OffsetLayout(
            archive_path="DATA/TEST.BIN",
            offsets=(0, 4),
            expected_size=4,
        )

        with self.assertRaisesRegex(ArchiveLayoutError, "3 bytes, expected 4"):
            list(slice_archive(b"abc", layout))


if __name__ == "__main__":
    unittest.main()
