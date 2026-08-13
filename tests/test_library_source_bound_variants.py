import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.srwz.library import apply_source_surface_replacements


ROOT = Path(__file__).resolve().parents[1]


class LibrarySourceBoundVariantTests(unittest.TestCase):
    def test_sirius_fallen_angel_title_does_not_duplicate_the_name(self) -> None:
        config = json.loads(
            (ROOT / "config/editorial/library-polish.json").read_text(
                encoding="utf-8"
            )
        )
        for before in (
            "诗翅西里乌斯",
            "诗翅西利乌斯",
            "诗翅<西里乌斯>",
            "诗翅<西利乌斯>",
            "诗翅（西里乌斯）",
            "诗翅",
        ):
            with self.subTest(before=before):
                after, applied = apply_source_surface_replacements(
                    before,
                    "詩翅＜シリウス＞",
                    config,
                )
                self.assertEqual(after, "诗翅（西利乌斯）")
                self.assertTrue(applied)

    def test_reviewed_library_uses_current_source_bound_terms(self) -> None:
        term_ids = [
            "people/speaker-22359c86b24b",
            "system/hangar",
            "organization/deava",
            "place/yapans-ceiling",
            "place/trinity-base",
            "place/atlandia",
            "place/genganam",
            "place/mountain-cycle",
            "place/ingressa",
            "place/urugsk",
        ]
        with tempfile.TemporaryDirectory() as temporary:
            report = Path(temporary) / "library-source-bound.json"
            command = [
                sys.executable,
                str(ROOT / "tools/apply_library_source_bound_glossary_variants.py"),
                "--report",
                str(report),
                "--fail-on-unresolved",
            ]
            for term_id in term_ids:
                command.extend(("--term-id", term_id))
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(ROOT / "tools")
            result = subprocess.run(
                command,
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            document = json.loads(report.read_text(encoding="utf-8"))

        self.assertGreater(document["matched_entry_count"], 0)
        self.assertEqual(document["changed_entry_count"], 0)
        self.assertEqual(document["unresolved_count"], 0)


if __name__ == "__main__":
    unittest.main()
