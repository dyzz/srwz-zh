import unittest
from pathlib import Path

from tools.render_srwz_tim2 import Tim2RenderError, require_work_png


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Tim2RenderCliTests(unittest.TestCase):
    def test_accepts_ignored_work_png(self):
        path = PROJECT_ROOT / "work" / "assets" / "render" / "test.png"

        self.assertEqual(require_work_png(path), path.resolve())

    def test_rejects_output_outside_work(self):
        path = PROJECT_ROOT / "build" / "unexpected.png"

        with self.assertRaisesRegex(Tim2RenderError, "must stay under"):
            require_work_png(path)

    def test_rejects_non_png_output(self):
        path = PROJECT_ROOT / "work" / "assets" / "render" / "test.tm2"

        with self.assertRaisesRegex(Tim2RenderError, "png suffix"):
            require_work_png(path)


if __name__ == "__main__":
    unittest.main()
