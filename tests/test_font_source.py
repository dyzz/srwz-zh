import copy
import json
import unittest
from pathlib import Path

from tools.srwz.font_source import FontSourceError, validate_font_lock


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FontSourceTests(unittest.TestCase):
    def test_first_five_font_is_pinned_to_lxgw_screen_release(self):
        config = json.loads(
            (
                PROJECT_ROOT / "config/fonts/first-five-font.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            config["font_lock"],
            "config/fonts/lxgw-neo-xihei-screen.lock.json",
        )
        lock = json.loads(
            (
                PROJECT_ROOT
                / "config/fonts/lxgw-neo-xihei-screen.lock.json"
            ).read_text(encoding="utf-8")
        )
        validate_font_lock(lock)
        self.assertEqual(lock["family"], "LXGW Neo XiHei Screen")
        self.assertEqual(lock["version"], "26.07.14")
        self.assertEqual(lock["license"]["spdx"], "IPA")
        self.assertEqual(len(lock["commit"]), 40)

    def test_font_lock_rejects_an_unapproved_download_host(self):
        lock = json.loads(
            (
                PROJECT_ROOT
                / "config/fonts/lxgw-neo-xihei-screen.lock.json"
            ).read_text(encoding="utf-8")
        )
        modified = copy.deepcopy(lock)
        modified["font"]["url"] = "https://example.com/font.ttf"
        with self.assertRaisesRegex(FontSourceError, "allowed source"):
            validate_font_lock(modified)
