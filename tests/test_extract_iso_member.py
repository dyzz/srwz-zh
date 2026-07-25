import unittest

from tools.extract_iso_member import safe_member_path


class IsoMemberPathTests(unittest.TestCase):
    def test_normalizes_backslashes(self):
        self.assertEqual(
            safe_member_path(r"DATA\STAGE.BIN").as_posix(),
            "DATA/STAGE.BIN",
        )

    def test_rejects_parent_traversal(self):
        with self.assertRaisesRegex(ValueError, "unsafe"):
            safe_member_path("../STAGE.BIN")

    def test_rejects_absolute_path(self):
        with self.assertRaisesRegex(ValueError, "relative"):
            safe_member_path("/DATA/STAGE.BIN")


if __name__ == "__main__":
    unittest.main()
