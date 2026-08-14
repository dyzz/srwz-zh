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
    def test_library_apply_skips_terms_outside_library_domain(self) -> None:
        source_row = {
            "id": "library-text/domain-filter",
            "source_text_sha256": "domain-filter",
            "model_source_text": "その大いなる力を発揮した。",
        }
        corpus = {
            "entries": [
                {
                    "id": source_row["id"],
                    "source_text_sha256": source_row["source_text_sha256"],
                    "translation": "发挥了强大力量。",
                    "glossary_refs": [],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "source.jsonl"
            reviewed = directory / "reviewed.json"
            report = directory / "report.json"
            source.write_text(
                json.dumps(source_row, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            reviewed.write_text(
                json.dumps(corpus, ensure_ascii=False),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(
                        ROOT
                        / "tools/apply_library_source_bound_glossary_variants.py"
                    ),
                    "--term-id",
                    "concept/great-power",
                    "--source",
                    str(source),
                    "--corpus",
                    str(reviewed),
                    "--report",
                    str(report),
                ],
                cwd=ROOT,
                env={**os.environ, "PYTHONPATH": str(ROOT / "tools")},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            document = json.loads(report.read_text(encoding="utf-8"))

        self.assertEqual(document["matched_entry_count"], 0)
        self.assertEqual(document["changed_entry_count"], 0)
        self.assertEqual(document["unresolved_count"], 0)

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
            "activity/lifting",
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
