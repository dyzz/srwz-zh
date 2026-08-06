import copy
import json
import unittest
from pathlib import Path

from tools.srwz.font_source import (
    FontSourceError,
    font_source_metadata,
    validate_font_lock,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FontSourceTests(unittest.TestCase):
    def test_first_five_font_is_pinned_to_noto_sans_cjk_sc_release(self):
        config = json.loads(
            (
                PROJECT_ROOT / "config/fonts/first-five-font.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            config["font_lock"],
            "config/fonts/noto-sans-cjk-sc.lock.json",
        )
        lock = json.loads(
            (
                PROJECT_ROOT
                / "config/fonts/noto-sans-cjk-sc.lock.json"
            ).read_text(encoding="utf-8")
        )
        validate_font_lock(lock)
        self.assertEqual(lock["family"], "Noto Sans CJK SC")
        self.assertEqual(lock["version"], "2.004")
        self.assertEqual(lock["license"]["spdx"], "OFL-1.1")
        self.assertEqual(len(lock["commit"]), 40)

    def test_font_lock_rejects_an_unapproved_download_host(self):
        lock = json.loads(
            (
                PROJECT_ROOT
                / "config/fonts/noto-sans-cjk-sc.lock.json"
            ).read_text(encoding="utf-8")
        )
        modified = copy.deepcopy(lock)
        modified["font"]["url"] = "https://example.com/font.ttf"
        with self.assertRaisesRegex(FontSourceError, "allowed source"):
            validate_font_lock(modified)

    def test_full_story_local_font_is_explicitly_noncommercial(self):
        lock = json.loads(
            (
                PROJECT_ROOT
                / "config/fonts/mf-dianhei-light-local-test.lock.json"
            ).read_text(encoding="utf-8")
        )
        validate_font_lock(lock)
        self.assertEqual(lock["source_kind"], "local-noncommercial-test")
        self.assertEqual(
            lock["distribution"], "local_noncommercial_test_only"
        )
        self.assertEqual(
            lock["license"]["spdx"],
            "LicenseRef-Noncommercial-Unverified",
        )
        metadata = font_source_metadata(lock)
        self.assertNotIn("commit", metadata)
        self.assertEqual(
            metadata["font_sha256"],
            "4deffedee63d21abc9b3cca8e17008216adbe5a11f14b6cd1990e306863d3208",
        )
