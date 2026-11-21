import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))


class SpSchedulingTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import patch
        import build_multilang as build

        # The scheduler removes stale receipts and writes go/cancel signals.
        # Running the suite beside a real build must leave its receipts alone.
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(build, "EARLY_FRONTENDS", directory))
        self.enterContext(patch.object(build, "GO", directory / "go"))

    def test_sp_only_schedules_components_then_one_disc_writer(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        import build_multilang as build

        args = SimpleNamespace(
            force_rebuild=True, out_dir=Path("/test"), release_version=None
        )
        languages = ["zh-hant-tw", "zh-hant-hk"]
        with (
            patch.object(
                build.subprocess, "run", return_value=SimpleNamespace(returncode=0)
            ),
            patch("freeze_title_version.refresh_current_badge", return_value="v-test"),
            patch.object(build, "build") as frontend,
            patch.object(build, "check_authored"),
            patch.object(build, "run") as stage,
            patch.object(build, "assemble") as legacy_assembly,
        ):
            build.build_discs(args, ["sp"], languages)

        self.assertCountEqual(
            [c.args for c in frontend.call_args_list],
            [("original", lang, "v-test", True, True) for lang in ("", *languages)],
        )
        writers = [
            c.args[1] for c in stage.call_args_list if c.args[0] == "sp-resources"
        ]
        self.assertEqual(len(writers), 1)
        self.assertIn("--component-frontends", writers[0])
        self.assertIn("--force-rebuild", writers[0])
        self.assertIn("/test/multilang-sp.iso", writers[0])
        legacy_assembly.assert_not_called()

    def test_all_editions_build_sp_beside_the_original_builds_and_release_it_after_the_checks(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        import build_multilang as build

        args = SimpleNamespace(force_rebuild=True, out_dir=Path("/test"), release_version=None)
        languages = ["zh-hant-tw", "zh-hant-hk"]
        events = []

        def frontend(edition, language, badge, force, frontend_only=False, early=False):
            events.append(("build", language, early))

        def sp_early(out, badge, force, langs, done):
            events.append(("early-started", build.GO.exists()))
            while not build.GO.exists():          # the real process waits for the go file the same way
                time.sleep(0.01)
            events.append(("early-published", str(out)))
            return True

        import time
        with (
            patch.object(build.subprocess, "run", return_value=SimpleNamespace(returncode=0)),
            patch("freeze_title_version.refresh_current_badge", return_value="v-test"),
            patch.object(build, "build", side_effect=frontend),
            patch.object(build, "build_sp_early", side_effect=sp_early),
            patch.object(build, "check_authored", side_effect=lambda *a, **k: events.append(("checked",))),
            patch.object(build, "run", side_effect=lambda name, cmd: events.append((name, cmd))),
            patch.object(build, "assemble", side_effect=lambda edition, out, force: events.append(("assemble", edition))),
        ):
            build.build_discs(args, ["original", "best", "sp"], languages)

        self.assertCountEqual([e for e in events if e[0] == "build"],
                              [("build", lang, True) for lang in ("", *languages)])
        self.assertIn(("early-started", False), events)       # before any go
        checked = events.index(("checked",))
        self.assertGreater(events.index(("early-published", "/test/multilang-sp.iso")), checked)
        self.assertFalse([e for e in events if e[0] == "sp-resources"])   # the disc is not built a second time
        self.assertCountEqual([e[1] for e in events if e[0] == "assemble"], ["original", "best"])
        self.assertTrue(all(i > checked for i, e in enumerate(events) if e[0] == "assemble"))

    def test_a_failed_edition_cancels_the_sp_disc(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        import time
        import build_multilang as build

        args = SimpleNamespace(force_rebuild=False, out_dir=Path("/test"), release_version=None)
        outcome = []

        def sp_early(out, badge, force, langs, done):
            cancel = build.GO.with_name(build.GO.name + ".cancel")
            while not (build.GO.exists() or cancel.exists()):
                time.sleep(0.01)
            outcome.append("published" if build.GO.exists() else "cancelled")
            return build.GO.exists()

        with (
            patch.object(build.subprocess, "run", return_value=SimpleNamespace(returncode=0)),
            patch("freeze_title_version.refresh_current_badge", return_value="v-test"),
            patch.object(build, "build"),
            patch.object(build, "build_sp_early", side_effect=sp_early),
            patch.object(build, "check_authored", side_effect=SystemExit("stale pictures")),
            patch.object(build, "run"),
            patch.object(build, "assemble") as assembly,
        ):
            with self.assertRaises(SystemExit):
                build.build_discs(args, ["original", "best", "sp"], ["zh-hant-tw", "zh-hant-hk"])
        self.assertEqual(outcome, ["cancelled"])
        assembly.assert_not_called()
