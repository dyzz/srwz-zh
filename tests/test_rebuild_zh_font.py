import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

# The command-line entry point resolves its sibling ``srwz`` package from the
# tools directory. Mirror that launch environment for direct unit imports.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from tools import rebuild_zh_font


class RebuildZhFontTests(unittest.TestCase):
    def test_parser_defaults_to_bounded_parallel_atlases(self):
        with patch.object(sys, "argv", ["rebuild_zh_font.py"]):
            args = rebuild_zh_font.parse_args()
        self.assertGreaterEqual(args.atlas_workers, 1)
        self.assertLessEqual(
            args.atlas_workers,
            rebuild_zh_font.MAX_ATLAS_WORKERS,
        )
        self.assertFalse(args.force_rebuild)
        self.assertEqual(args.cache, rebuild_zh_font.DEFAULT_CACHE)

    def test_parser_rejects_non_positive_atlas_workers(self):
        with patch.object(
            sys,
            "argv",
            ["rebuild_zh_font.py", "--atlas-workers", "0"],
        ):
            with self.assertRaises(SystemExit):
                rebuild_zh_font.parse_args()

    def test_serial_mode_keeps_story_before_atlas_order(self):
        events = []

        def record_run(*arguments):
            events.append(("run", arguments))

        def record_atlas(reference, **kwargs):
            events.append(("atlas", reference, kwargs))

        with (
            patch.object(rebuild_zh_font, "_run", side_effect=record_run),
            patch.object(
                rebuild_zh_font,
                "_build_atlas_job",
                side_effect=record_atlas,
            ),
        ):
            rebuild_zh_font._build_story_and_atlases(
                "config/story-component.json",
                ["atlas-a.json", "atlas-b.json"],
                refresh_manifest=True,
                refresh_asset_ratchets=False,
                atlas_workers=1,
            )

        self.assertEqual(events[0][0], "run")
        self.assertEqual([event[1] for event in events[1:]], [
            "atlas-a.json",
            "atlas-b.json",
        ])

    def test_parallel_mode_runs_every_registered_job(self):
        events = []

        def record_run(*arguments):
            events.append(("run", arguments))

        def record_atlas(reference, **kwargs):
            events.append(("atlas", reference, kwargs))

        with (
            patch.object(rebuild_zh_font, "_run", side_effect=record_run),
            patch.object(
                rebuild_zh_font,
                "_build_atlas_job",
                side_effect=record_atlas,
            ),
        ):
            rebuild_zh_font._build_story_and_atlases(
                "config/story-component.json",
                ["atlas-a.json", "atlas-b.json"],
                refresh_manifest=False,
                refresh_asset_ratchets=True,
                atlas_workers=2,
            )

        self.assertEqual(
            [event[0] for event in events].count("run"),
            1,
        )
        self.assertEqual(
            {event[1] for event in events if event[0] == "atlas"},
            {"atlas-a.json", "atlas-b.json"},
        )

    def test_integrated_component_defaults_to_locked_member_cache(self):
        arguments = rebuild_zh_font._integrated_component_args(
            "config/full-story-components.json",
            refresh_manifest=False,
            force_rebuild=False,
        )
        self.assertIn("--incremental", arguments)
        self.assertIn("--force", arguments)
        self.assertNotIn("--refresh-manifest", arguments)

    def test_force_rebuild_disables_incremental_component_reuse(self):
        arguments = rebuild_zh_font._integrated_component_args(
            "config/full-story-components.json",
            refresh_manifest=True,
            force_rebuild=True,
        )
        self.assertNotIn("--incremental", arguments)
        self.assertIn("--force", arguments)
        self.assertIn("--refresh-manifest", arguments)

    def test_integrated_component_cache_requires_incremental_state(self):
        with tempfile.TemporaryDirectory(dir=rebuild_zh_font.PROJECT_ROOT) as tmp:
            component_root = Path(tmp).relative_to(
                rebuild_zh_font.PROJECT_ROOT
            )
            config = {"outputs": {"component_root": str(component_root)}}
            self.assertFalse(
                rebuild_zh_font._integrated_component_cache_ready(config)
            )
            (Path(tmp) / "incremental-state.json").write_text(
                "{}\n",
                encoding="utf-8",
            )
            self.assertTrue(
                rebuild_zh_font._integrated_component_cache_ready(config)
            )

    def test_cache_requires_standard_local_full_chain_mode(self):
        with patch.object(
            sys,
            "argv",
            ["rebuild_zh_font.py", "--skip-fetch"],
        ):
            args = rebuild_zh_font.parse_args()
        self.assertTrue(rebuild_zh_font._cache_eligible(args))

        for extra in (
            "--skip-assets",
            "--refresh-manifests",
            "--force-rebuild",
        ):
            with patch.object(
                sys,
                "argv",
                ["rebuild_zh_font.py", "--skip-fetch", extra],
            ):
                args = rebuild_zh_font.parse_args()
            self.assertFalse(rebuild_zh_font._cache_eligible(args), extra)

    def test_main_cache_hit_skips_build_commands(self):
        with (
            patch.object(
                sys,
                "argv",
                ["rebuild_zh_font.py", "--skip-fetch"],
            ),
            patch.object(
                rebuild_zh_font,
                "_load",
                return_value={"integrated_component": "config/full.json"},
            ),
            patch.object(
                rebuild_zh_font,
                "_chain_cache_inventory",
                return_value={Path(__file__).resolve()},
            ),
            patch.object(
                rebuild_zh_font,
                "validate_verified_cache",
                return_value=SimpleNamespace(
                    hit=True,
                    checked_file_count=1,
                    checked_byte_count=123,
                ),
            ),
            patch.object(
                rebuild_zh_font,
                "_run",
                side_effect=AssertionError("cache hit must skip subprocesses"),
            ),
        ):
            self.assertEqual(rebuild_zh_font.main(), 0)


if __name__ == "__main__":
    unittest.main()
