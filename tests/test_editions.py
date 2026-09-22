from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build_editions
import verify_editions
from srwz.edition import BuildContext, EditionError, EditionProfile, load_json, load_release_profiles, project_path
from srwz.release_inputs import SOURCE_ROOTS, freeze_inputs, sha256_file, source_inventory


REPO = Path(__file__).resolve().parents[1]


class EditionTests(unittest.TestCase):
    def setUp(self):
        publisher = patch.object(build_editions, "publish_daily_test", return_value={})
        self.publisher = publisher.start()
        self.addCleanup(publisher.stop)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        for name in SOURCE_ROOTS:
            (self.root / name).mkdir(parents=True, exist_ok=True)
        for name in ("config/editions", "config/release"):
            for path in (REPO / name).rglob("*.json"):
                if name == "config/release" and path.name != "dual-current.json":
                    continue
                target = self.root / path.relative_to(REPO)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
        (self.root / "corpus/line.txt").write_text("shared translation")

    def profiles(self):
        return load_release_profiles(self.root, build_editions.DEFAULT_CONFIG, ("original", "best"))

    def freeze(self):
        with patch("srwz.release_inputs.subprocess.check_output", return_value="test-source-head\n"):
            return freeze_inputs(self.root)

    def test_plan_has_two_identities_without_creating_outputs(self):
        result = build_editions.build(self.root, build_editions.DEFAULT_CONFIG, ("original", "best"), plan=True)
        self.assertEqual([row["available"] for row in result["targets"]], [True, True])
        self.assertFalse((self.root / "work").exists())

    def test_sp_plan_and_output_keep_native_identity(self):
        result = build_editions.build(self.root, build_editions.DEFAULT_CONFIG, ("original", "best", "sp"), plan=True)
        self.assertEqual(result["targets"][-1]["executable"], "SLPS_259.20")
        profile, = load_release_profiles(self.root, build_editions.DEFAULT_CONFIG, ("sp",))
        context = BuildContext(self.root, profile, "a" * 64)
        self.assertEqual(context.output_iso, self.root / "build/iso/special-disc/sp-current.iso")
        self.assertFalse((self.root / "work").exists())

    def test_sp_only_does_not_build_main_game_frontend(self):
        with patch.object(build_editions, "verify_disc"), patch.object(build_editions, "locked_sp_inputs", return_value=()), \
                patch.object(build_editions, "build_original") as original, \
                patch.object(build_editions, "build_sp", return_value={"edition_id": "sp"}) as sp, \
                patch("srwz.release_inputs.subprocess.check_output", return_value="test-head\n"):
            batch = build_editions.build(self.root, build_editions.DEFAULT_CONFIG, ("sp",))
        original.assert_not_called()
        self.assertEqual(sp.call_count, 1)
        self.assertEqual(batch["results"], [{"edition_id": "sp", "daily_test": {}}])
        self.publisher.assert_called_once()
        self.assertGreaterEqual(batch["timing"]["total_seconds"], batch["timing"]["editions"]["sp"]["seconds"])

    def test_failed_sp_never_reports_successful_batch(self):
        with patch.object(build_editions, "verify_disc"), patch.object(build_editions, "locked_sp_inputs", return_value=()), \
                patch.object(build_editions, "build_sp", side_effect=EditionError("SP readback failed")), \
                patch("srwz.release_inputs.subprocess.check_output", return_value="test-head\n"):
            with self.assertRaisesRegex(EditionError, "SP readback failed"):
                build_editions.build(self.root, build_editions.DEFAULT_CONFIG, ("sp",))
        self.assertFalse((self.root / "manifests/editions/sp/current.json").exists())
        batch = json.loads(next((self.root / "work/editions").glob("*/sp.json")).read_text())
        self.assertEqual(batch["status"], "failed")

    def test_sp_baseline_lock_rejects_missing_or_changed_input(self):
        from srwz.sp_edition import locked_sp_inputs
        with self.assertRaisesRegex(EditionError, "SP locked dependency missing or changed"):
            locked_sp_inputs(self.root)

    def test_extra_baseline_and_editorial_inputs_are_frozen(self):
        paths = ("work/build/special-disc/baselines/test.xdelta", "config/editorial/special-disc/test.json")
        for raw in paths:
            path = self.root / raw
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"reviewed dependency")
        with patch("srwz.release_inputs.subprocess.check_output", return_value="test-head\n"):
            snapshot = freeze_inputs(self.root, paths)
        (self.root / paths[0]).write_bytes(b"later mutation")
        target = self.root / "private"
        snapshot.materialize(target)
        self.assertEqual((target / paths[0]).read_bytes(), b"reviewed dependency")
        self.assertEqual((target / paths[1]).read_bytes(), b"reviewed dependency")

    def test_best_is_rejected_before_any_disc_read_or_output_write(self):
        path = self.root / "config/editions/best/edition.json"
        profile = json.loads(path.read_text())
        profile["adapter"] = None
        path.write_text(json.dumps(profile))
        with patch.object(build_editions, "verify_disc") as verify:
            with self.assertRaisesRegex(EditionError, "not implemented"):
                build_editions.build(self.root, build_editions.DEFAULT_CONFIG, ("original", "best"))
            verify.assert_not_called()
        self.assertFalse((self.root / "work").exists())

    def test_best_cannot_be_routed_through_original_adapter(self):
        path = self.root / "config/editions/best/edition.json"
        data = json.loads(path.read_text())
        data["adapter"] = "original-production-v1"
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(EditionError, "Original adapter cannot build BEST"):
            self.profiles()

    def test_wrong_member_layout_or_data_policy_fails_closed(self):
        path = self.root / "config/editions/original/edition.json"
        baseline = path.read_text()
        for group, key, value in (("layout", "stage_base", "0x756EF0"), ("executable", "member", "SLPS_732.70")):
            data = json.loads(baseline)
            data[group][key] = value
            path.write_text(json.dumps(data))
            with self.subTest(group=group), self.assertRaisesRegex(EditionError, "policy mismatch"):
                self.profiles()

    def test_best_only_and_reversed_order_share_one_frontend(self):
        for requested in (("best",),("best","original")):
            with self.subTest(requested=requested):
                def compiled(context, snapshot, **kwargs):
                    return {"edition_id":context.profile.edition_id,"input_digest":snapshot.digest}
                def native(context, snapshot, common, result):
                    self.assertEqual(result["input_digest"],snapshot.digest)
                    self.assertEqual(common.profile.edition_id,"original")
                    return compiled(context,snapshot)
                with patch.object(build_editions,"verify_disc"), patch.object(build_editions,"verify_original_adapter_config"), \
                        patch.object(build_editions,"build_original",side_effect=compiled) as original, \
                        patch.object(build_editions,"build_best",side_effect=native) as best, \
                        patch("srwz.release_inputs.subprocess.check_output",return_value="test-head\n"):
                    batch = build_editions.build(self.root,build_editions.DEFAULT_CONFIG,requested)
                self.assertEqual(original.call_count,1)
                self.assertEqual(best.call_count,1)
                self.assertEqual([r["edition_id"] for r in batch["results"]],list(requested))

    def test_failed_best_never_reports_a_successful_batch(self):
        with patch.object(build_editions,"verify_disc"), patch.object(build_editions,"verify_original_adapter_config"), \
                patch.object(build_editions,"build_original",return_value={"edition_id":"original"}), \
                patch.object(build_editions,"build_best",side_effect=EditionError("native overlap")), \
                patch("srwz.release_inputs.subprocess.check_output",return_value="test-head\n"):
            with self.assertRaisesRegex(EditionError,"native overlap"):
                build_editions.build(self.root,build_editions.DEFAULT_CONFIG,("original","best"))
        batch = json.loads(next((self.root/"work/editions").glob("*/original-best.json")).read_text())
        self.assertEqual(batch["status"],"failed")
        self.assertFalse((self.root/"manifests/editions/best/current.json").exists())
        # A later backend failure must not leave the already promoted Original
        # ISO paired with an older current receipt.
        self.assertEqual(json.loads((self.root/"manifests/editions/original/current.json").read_text()),
                         {"edition_id": "original", "daily_test": {}})

    def test_duplicate_keys_and_duplicate_targets_are_rejected(self):
        p = self.root / "config/duplicate.json"
        p.write_text('{"edition": "original", "edition": "best"}')
        with self.assertRaisesRegex(EditionError, "duplicate JSON"):
            load_json(p)
        with self.assertRaisesRegex(EditionError, "unique"):
            load_release_profiles(self.root, build_editions.DEFAULT_CONFIG, ("original", "original"))

    def test_context_output_cache_and_workspace_are_disjoint(self):
        original, best = self.profiles()
        a, b = (BuildContext(self.root, p, "a" * 64) for p in (original, best))
        for field in ("run_root", "project_root", "cache_root", "output_iso", "receipt"):
            self.assertNotEqual(getattr(a, field), getattr(b, field))
        self.assertNotEqual(a.run_root, BuildContext(self.root, original, "b" * 64).run_root)
        self.assertNotEqual(a.output_iso, self.root / "build/iso/zh-release-full-story/current-original.iso")

    def test_all_iso_bearing_workspaces_are_under_build(self):
        for profile in load_release_profiles(self.root, build_editions.DEFAULT_CONFIG, ("original", "best", "sp")):
            context = BuildContext(self.root, profile, "a" * 64)
            self.assertTrue(context.project_root.is_relative_to(self.root / "build/editions"))
            self.assertEqual(context.project_root.parent, context.run_root)
            self.assertTrue(context.output_iso.is_relative_to(self.root / "build/iso"))

    def test_symlinked_output_root_cannot_escape_project(self):
        with tempfile.TemporaryDirectory() as external:
            (self.root / "work").symlink_to(external, target_is_directory=True)
            with self.assertRaisesRegex(EditionError, "escapes"):
                project_path(self.root, "work/cache/editions/original", "work/cache")

    def test_output_cannot_alias_the_legacy_iso_even_inside_project(self):
        original, _ = self.profiles()
        context = BuildContext(self.root, original, "a" * 64)
        output = context.output_iso
        legacy = self.root / "build/iso/zh-release-full-story/current-original.iso"
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(b"legacy")
        output.parent.mkdir(parents=True)
        output.symlink_to(legacy)
        with patch.object(build_editions, "verify_disc") as verify:
            with self.assertRaisesRegex(EditionError, "must not alias"):
                build_editions.build(self.root, build_editions.DEFAULT_CONFIG, ("original",))
            verify.assert_not_called()
        self.assertEqual(legacy.read_bytes(), b"legacy")

    def test_snapshot_is_frozen_and_private_copy_is_not_a_hardlink(self):
        snapshot = self.freeze()
        source = self.root / "corpus/line.txt"
        source.write_text("later polish")
        target = self.root / "work/private"
        snapshot.materialize(target)
        self.assertEqual((target / "corpus/line.txt").read_text(), "shared translation")
        (target / "corpus/line.txt").write_text("private write")
        self.assertEqual(source.read_text(), "later polish")
        self.assertEqual((snapshot.project_root / "corpus/line.txt").read_text(), "shared translation")
        self.assertNotEqual(self.freeze().digest, snapshot.digest)

    def test_snapshot_corruption_or_extra_private_corpus_is_rejected(self):
        snapshot = self.freeze()
        target = self.root / "work/private"
        snapshot.materialize(target)
        (target / "corpus/untracked.txt").write_text("not captured")
        with self.assertRaisesRegex(EditionError, "outside the frozen snapshot"):
            snapshot.materialize(target)
        (snapshot.project_root / "corpus/line.txt").write_text("corrupt")
        with self.assertRaisesRegex(EditionError, "frozen input drift"):
            self.freeze()

    def test_concurrent_input_change_during_capture_is_rejected(self):
        baseline = source_inventory(self.root)
        changed = [*baseline, {"path": "corpus/new.txt"}]
        with patch("srwz.release_inputs.source_inventory", side_effect=[baseline, changed]):
            with self.assertRaisesRegex(EditionError, "changed during snapshot"):
                self.freeze()
        self.assertEqual(list((self.root / "work/build/shared").iterdir()), [])

    def test_source_iso_mismatch_does_not_enter_the_iso_parser(self):
        original, _ = self.profiles()
        path = self.root / original.source_iso.path
        path.parent.mkdir(parents=True)
        path.write_bytes(b"wrong disc")
        with patch.object(build_editions, "scan_iso9660") as scan:
            with self.assertRaisesRegex(EditionError, "source ISO identity mismatch"):
                build_editions.verify_disc(self.root, original)
            scan.assert_not_called()

    def test_lock_prevents_two_writers_for_same_edition(self):
        lock = self.root / "work/cache/original.lock"
        with build_editions.edition_lock(lock):
            with self.assertRaisesRegex(EditionError, "another build owns"):
                with build_editions.edition_lock(lock):
                    self.fail("second writer acquired edition lock")

    def test_relocated_cmake_cache_is_removed_only_in_private_build_directory(self):
        source = self.root / "work/toolchain/mkps2iso/source"
        build = source / "build"
        build.mkdir(parents=True)
        (source / "CMakeLists.txt").write_text("source retained")
        (build / "CMakeCache.txt").write_text("CMAKE_HOME_DIRECTORY:INTERNAL=/old/source\n")
        config = {"toolchain": {"source_dir": "work/toolchain/mkps2iso/source"}}
        build_editions.reset_relocated_cmake(self.root.resolve(), config)
        self.assertFalse(build.exists())
        self.assertTrue((source / "CMakeLists.txt").is_file())

    def test_valid_cmake_cache_is_reused(self):
        source = (self.root / "work/toolchain/mkps2iso/source").resolve()
        build = source / "build"
        build.mkdir(parents=True)
        cache = build / "CMakeCache.txt"
        cache.write_text(f"CMAKE_HOME_DIRECTORY:INTERNAL={source}\nCMAKE_CACHEFILE_DIR:INTERNAL={build}\n")
        build_editions.reset_relocated_cmake(self.root.resolve(), {"toolchain": {"source_dir": "work/toolchain/mkps2iso/source"}})
        self.assertTrue(cache.exists())

    def receipt_fixture(self, edition="original"):
        snapshot = self.freeze()
        original, = load_release_profiles(self.root, build_editions.DEFAULT_CONFIG, (edition,))
        context = BuildContext(self.root, original, snapshot.digest)
        context.output_iso.parent.mkdir(parents=True)
        context.output_iso.write_bytes(b"fixture for receipt bindings, not ISO parsing")
        output = {"path": context.output_iso.relative_to(self.root).as_posix(),
                  "size": context.output_iso.stat().st_size, "sha256": sha256_file(context.output_iso)}
        proof = context.project_root / "manifests/readback.json"
        proof.parent.mkdir(parents=True)
        proof.write_text(json.dumps({"status": "full_story_final_iso_static_content_readback_passed", "iso": output}))
        batch = {"status": "requested_editions_static_validated_runtime_pending",
                 "input_snapshot": (snapshot.root / "inputs.json").relative_to(self.root).as_posix(),
                 "input_digest": snapshot.digest, "release_config": build_editions.DEFAULT_CONFIG,
                 "requested_editions": [edition], "results": [{
                     "edition_id": edition, "input_digest": snapshot.digest,
                     "edition_contract_sha256": original.contract_sha256,
                     "source_iso_sha256": original.source_iso.sha256, "adapter": original.adapter,
                     "status": "edition_iso_static_validated_runtime_pending", "output": output,
                     "readback": {"path": proof.relative_to(self.root).as_posix(), "sha256": sha256_file(proof)},
                 }]}
        manifest = self.root / "batch.json"
        manifest.write_text(json.dumps(batch))
        return manifest, batch, context, proof

    def test_sp_batch_accepts_published_status_and_still_requires_semantic_validation(self):
        manifest, batch, context, proof = self.receipt_fixture("sp")
        readback = json.loads(proof.read_text())
        readback["status"] = "all_bound_text_reread_from_final_iso_runtime_pending"
        proof.write_text(json.dumps(readback))
        batch["results"][0]["readback"]["sha256"] = sha256_file(proof)
        manifest.write_text(json.dumps(batch))
        with patch.object(verify_editions, "locked_sp_inputs"), \
                patch.object(verify_editions, "validate_sp_readback") as validate:
            result = verify_editions.verify_batch(self.root, manifest)
            self.assertEqual(result["verified_editions"], ["sp"])
            validate.assert_called_once_with(context.project_root, readback)
            validate.side_effect = EditionError("SP corpus or font coverage incomplete")
            with self.assertRaisesRegex(EditionError, "coverage incomplete"):
                verify_editions.verify_batch(self.root, manifest)

    def test_receipt_verifies_actual_iso_and_does_not_claim_both_editions(self):
        manifest, _, _, _ = self.receipt_fixture()
        result = verify_editions.verify_batch(self.root, manifest)
        self.assertEqual(result["verified_editions"], ["original"])
        self.assertFalse(result["both_editions"])
        self.assertEqual(result["runtime"], "not_tested")

    def test_incomplete_or_cross_input_results_are_rejected(self):
        manifest, baseline, _, _ = self.receipt_fixture()
        cases = (
            ("failed", lambda b: b.update(status="failed")),
            ("missing result", lambda b: b.update(results=[])),
            ("cross input", lambda b: b["results"][0].update(input_digest="a" * 64)),
            ("cross disc", lambda b: b["results"][0].update(source_iso_sha256="b" * 64)),
            ("different contract", lambda b: b["results"][0].update(edition_contract_sha256="c" * 64)),
            ("different edition", lambda b: b["results"][0].update(edition_id="best")),
        )
        for label, mutate in cases:
            batch = json.loads(json.dumps(baseline))
            mutate(batch)
            manifest.write_text(json.dumps(batch))
            with self.subTest(label=label), self.assertRaises(EditionError):
                verify_editions.verify_batch(self.root, manifest)

    def test_receipt_rejects_stale_output_bytes(self):
        manifest, _, context, _ = self.receipt_fixture()
        context.output_iso.write_bytes(b"another build")
        with self.assertRaisesRegex(EditionError, "stale or misbound"):
            verify_editions.verify_batch(self.root, manifest)

    def test_receipt_rejects_readback_drift_or_binding_to_another_iso(self):
        manifest, batch, _, proof = self.receipt_fixture()
        data = json.loads(proof.read_text())
        data["iso"]["sha256"] = "a" * 64
        proof.write_text(json.dumps(data))
        with self.assertRaisesRegex(EditionError, "receipt drift"):
            verify_editions.verify_batch(self.root, manifest)
        batch["results"][0]["readback"]["sha256"] = sha256_file(proof)
        manifest.write_text(json.dumps(batch))
        with self.assertRaisesRegex(EditionError, "different ISO"):
            verify_editions.verify_batch(self.root, manifest)

    def test_receipt_rejects_modified_frozen_source(self):
        manifest, batch, _, _ = self.receipt_fixture()
        project = (self.root / batch["input_snapshot"]).parent / "project"
        (project / "corpus/line.txt").write_text("later translation")
        with self.assertRaisesRegex(EditionError, "frozen input drift"):
            verify_editions.verify_batch(self.root, manifest)


if __name__ == "__main__":
    unittest.main()
