import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))


class SpSchedulingTests(unittest.TestCase):
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


class SpResourceCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/zh_hant"))
        import build_sp_resources

        cls.builder = build_sp_resources

    def test_hong_kong_binds_shared_taiwan_literals_and_its_own_subtitles(self):
        from unittest.mock import patch

        build = self.builder
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            components = root / "components"
            components.mkdir()
            member = components / "STAGE.BIN"
            member.write_text("verified member bytes")
            config = root / "config/iso/zh-release-current-build.json"
            config.parent.mkdir(parents=True)
            config.write_text('{"replacements":[{"member":"STAGE.BIN"}]}')
            tw = {
                "path": "corpus/zh-hant/special-disc/battle-lines.json",
                "sha256": "original",
            }
            hk = {
                "path": "corpus/zh-hant-hk/special-disc/battle-lines.json",
                "sha256": "original",
            }
            with (
                patch.object(build, "ROOT", root),
                patch.object(build, "locked_sp_inputs", return_value=()),
                patch.object(build, "source_inventory", return_value=[tw, hk]),
                patch.object(build, "_answer_key", return_value=components),
                patch.object(build, "texture_sources", return_value=[]),
                patch.object(
                    build, "taiwan_data_link_literals", return_value={"page": "shared"}
                ) as shared,
                patch.object(
                    build,
                    "sha256_file",
                    side_effect=lambda p: p.read_bytes().hex()
                    if p.is_file()
                    else "fixed",
                ),
            ):

                def fingerprint(region):
                    return build.input_state(region, "v-test", False)[2]

                previous_hk, previous_tw = fingerprint("hk"), fingerprint("tw")
                tw["sha256"] = "edited"
                self.assertEqual(fingerprint("hk"), previous_hk)
                self.assertNotEqual(fingerprint("tw"), previous_tw)
                shared.return_value = {"page": "changed"}
                self.assertNotEqual(fingerprint("hk"), previous_hk)
                shared.return_value = {"page": "shared"}
                hk["sha256"] = "edited"
                self.assertNotEqual(fingerprint("hk"), previous_hk)
                hk["sha256"] = "original"
                (components / "component-validation.json").write_text(
                    "updated diagnostic identity"
                )
                self.assertEqual(fingerprint("hk"), previous_hk)
                member.write_text("changed member")
                self.assertNotEqual(fingerprint("hk"), previous_hk)

    def test_pruning_keeps_active_and_two_recent_successes(self):
        import json
        import os
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            region = cache / "tw"
            roots = [region / f"{i:064x}" for i in range(4)]
            relative = Path("inputs-good/work/build/resource-components/final.spview")
            for i, directory in enumerate(roots):
                view = directory / relative
                view.parent.mkdir(parents=True)
                view.touch()
                seal = directory / "verified.json"
                seal.write_text(json.dumps({"path": str(relative)}))
                os.utime(seal, (i + 1, i + 1))
            superseded = (
                roots[0] / "inputs-old/work/build/resource-components/final.spview"
            )
            superseded.parent.mkdir(parents=True)
            superseded.touch()
            pending = region / "unfinished" / "inputs-in-progress"
            pending.mkdir(parents=True)

            with patch.object(self.builder, "CACHE", cache):
                self.builder.prune_resources("tw", roots[0])

            self.assertEqual([p.exists() for p in roots], [True, False, True, True])
            self.assertTrue(all((roots[i] / relative).is_file() for i in (0, 2, 3)))
            self.assertFalse(superseded.exists())
            self.assertTrue(pending.exists())
