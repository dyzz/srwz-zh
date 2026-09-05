import hashlib
import json
import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from tools import build_full_story_components as full
from tools import build_text_update_iso as text_build
from tools import ui_atlas
from tools import rebuild_zh_font
from tools import build_iso
from tools.srwz.patch_audit import PatchAuditError, changed_offsets
from tools.srwz.psmt4 import Psmt4Error, swizzle_psmt4, unswizzle_psmt4


def write_json(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return lock(root, path)


def lock(root, path):
    data = path.read_bytes()
    return {"path": str(path.relative_to(root)), "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest()}


class BuildOptimizationTests(unittest.TestCase):
    def test_cached_iso_noop_still_requires_expected_output_hash(self):
        config = {
            "source_iso": {"path": "source.iso"},
            "replacements": [{"member": "DATA/STAGE.BIN", "sha256": "unchanged"}],
            "output": {"path": "build/candidate.iso", "expected_sha256": "wrong"},
        }
        previous = {"replacements": config["replacements"],
                    "output_iso": {"sha256": "actual"},
                    "layout": {"member_manifest_sha256": "members"}}
        with patch.object(build_iso, "_load_iso_cache", return_value=previous), \
             patch.object(build_iso, "scan_iso9660"), \
             patch.object(build_iso, "validate_replacement_sector_budget"):
            with self.assertRaisesRegex(build_iso.IsoBuildError, "expected_sha256"):
                build_iso._build_incremental_iso(config, {})

    def test_iso_cache_reuses_hash_changes_but_invalidates_size_code_and_file_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "source.iso").write_bytes(b"original disc")
            (root / "output.iso").write_bytes(b"validated output")
            (root / "report.json").write_text(json.dumps({"member_hashes": {"DATA/STAGE.BIN": "old"}}))
            config = {"source_iso": {"path": "source.iso"}, "replacements": [
                {"member": "DATA/STAGE.BIN", "source": "stage.bin", "size": 16, "sha256": "old"}],
                "output": {"path": "output.iso", "report": "report.json"}}
            with patch.object(build_iso, "PROJECT_ROOT", root), \
                 patch.object(build_iso, "_iso_implementation_signature", return_value="code-v1"):
                build_iso._record_iso_cache(config, root / "report.json")
                self.assertIsNotNone(build_iso._load_iso_cache(config))
                config["replacements"][0]["sha256"] = "new"
                self.assertIsNotNone(build_iso._load_iso_cache(config))
                config["replacements"][0]["size"] += 1
                self.assertIsNone(build_iso._load_iso_cache(config))
                config["replacements"][0]["size"] -= 1
                with patch.object(build_iso, "_iso_implementation_signature", return_value="code-v2"):
                    self.assertIsNone(build_iso._load_iso_cache(config))
                (root / "output.iso").write_bytes(b"damaged contents")
                self.assertIsNone(build_iso._load_iso_cache(config))
                build_iso._record_iso_cache(config, root / "report.json")
                (root / "source.iso").write_bytes(b"different disc")
                self.assertIsNone(build_iso._load_iso_cache(config))
                build_iso._record_iso_cache(config, root / "report.json")
                (root / "report.json").write_text("{}")
                self.assertIsNone(build_iso._load_iso_cache(config))
                config["release_tag"] = "frozen-release"
                self.assertIsNone(build_iso._load_iso_cache(config))

    def test_stage_reuse_invalidates_changed_chunks_and_postprocessors(self):
        state = {"stage_chunk_sha256": ["a", "b", "c"]}
        report = {"stage_postprocess_signature": "code-v1", "remaining_ui": {
            "stage_default_formation": {"chunks": [{"rewrite_summary": {}}]}}}
        with patch.object(full, "_stage_postprocess_signature", return_value="code-v1"), \
             patch.object(full, "_stage_chunk_hashes", return_value=["a", "changed", "c"]):
            self.assertEqual(full._incremental_stage_indices({}, state, report, ["input:stage"]), {1})
            self.assertIsNone(full._incremental_stage_indices({}, state, report, ["input:stage_overviews"]))
            self.assertIsNone(full._incremental_stage_indices({}, {}, report, ["input:stage"]))
            report["stage_postprocess_signature"] = "old-code"
            self.assertIsNone(full._incremental_stage_indices({}, state, report, ["input:stage"]))

    def test_stage_zero_changes_use_full_postprocessing(self):
        report = {"stage_postprocess_signature": "code"}
        with patch.object(full, "_stage_postprocess_signature", return_value="code"), \
             patch.object(full, "_stage_chunk_hashes", return_value=["changed", "b"]):
            self.assertIsNone(full._incremental_stage_indices(
                {}, {"stage_chunk_sha256": ["a", "b"]}, report, ["input:stage"]))

    def test_sparse_diff_matches_byte_oracle_across_block_edges(self):
        rng = random.Random(42)
        for size in (0, 1, 4095, 4096, 4097, 16001):
            before = bytes(rng.randrange(256) for _ in range(size))
            for dense in (False, True):
                after = bytearray(before)
                positions = range(size) if dense else (0, 4095, 4096, 8192, size - 1)
                for offset in positions:
                    if 0 <= offset < size:
                        after[offset] ^= 255
                expected = tuple(i for i, pair in enumerate(zip(before, after)) if pair[0] != pair[1])
                self.assertEqual(changed_offsets(before, bytes(after)), expected)
        with self.assertRaises(PatchAuditError):
            changed_offsets(b"a", b"ab")

    def test_psmt4_matches_preoptimization_golden_layouts(self):
        cases = (
            (32, 32, False, "c299cd3679ae2e5bca94e9b227f354e4886cf8fbf879fd74340bfb54a11fe249"),
            (64, 64, False, "3e18c4f732bb8e98999ba192bcfa2c0a7a96f48b41a0b6c0256fea10e6536d8d"),
            (128, 128, False, "8e8a5b3d714e3956f8ddf9e5c903623200a9ad79d1d6e0bf60ee9c95eec189e4"),
            (256, 256, False, "12e4e8b97b5a6ae62f60ed31957b90d2ff45605e42b56783002bd31cb6b5d703"),
            (512, 256, True, "9bc1893ec384d3552467bebe67cf2efad62940609184c722baba0769e60bcdc8"),
            (256, 512, True, "aae86d95e037ffc8cd60fd66c5723dbb9c3d6cb224461218ee7d26deca3e8eb3"),
        )
        for width, height, row_major, digest in cases:
            logical = bytes((i * 7 + i // width) % 16 for i in range(width * height))
            for _ in range(2):  # Both the first validation and the cached permutation.
                stored = swizzle_psmt4(logical, width, height, row_major_pages=row_major)
                self.assertEqual(hashlib.sha256(stored).hexdigest(), digest)
                self.assertEqual(unswizzle_psmt4(stored, width, height, row_major_pages=row_major), logical)
        with self.assertRaises(Psmt4Error):
            swizzle_psmt4(bytes([16]) * 1024, 32, 32)
        with self.assertRaises(Psmt4Error):
            unswizzle_psmt4(b"", 32, 32)

    def test_font_selection_drift_does_not_invalidate_binary_consumers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            proposal = {"assignments": [{"character": "中", "code": "8140"}], "ui_selection": {"count": 1}}
            signature = full.font_binary_signature(proposal)
            prior_lock = write_json(root, "proposal.json", proposal)
            proposal["ui_selection"]["count"] = 2
            write_json(root, "proposal.json", proposal)
            arguments = dict(baseline_config={}, current_config={}, baseline_remaining_ui={},
                             current_remaining_ui={}, prior_report={"inputs": {"full_story_font_proposal": prior_lock}},
                             baseline_font_signature=signature)
            with patch.object(full, "PROJECT_ROOT", root):
                affected, reasons = full._plan_incremental_members(**arguments)
                self.assertEqual(affected, set())
                self.assertEqual(reasons, ["input:full_story_font_proposal"])
                proposal["assignments"][0]["code"] = "8141"
                write_json(root, "proposal.json", proposal)
                affected, _ = full._plan_incremental_members(**arguments)
                self.assertIn(full.VT1_MEMBER, affected)
                self.assertIn(full.STAGE_MEMBER, affected)

    def test_metadata_rebind_updates_nested_locks_without_changing_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            config = write_json(root, "config.json", {})
            proposal = write_json(root, "proposal.json", {"ui_selection": 1})
            report = {"inputs": {"config": config, "full_story_font_proposal": proposal},
                      "composition": {"release_proposal": proposal},
                      "outputs": {"DATA/STAGE.BIN": {"sha256": "unchanged"}}}
            current = write_json(root, "proposal.json", {"ui_selection": 2})
            with patch.object(full, "PROJECT_ROOT", root):
                rebound = full._rebind_metadata_report(root / "config.json", report)
            self.assertEqual(rebound["composition"]["release_proposal"], current)
            self.assertEqual(rebound["outputs"], report["outputs"])
            self.assertEqual(report["inputs"]["full_story_font_proposal"], proposal)

    def test_full_chain_cache_includes_final_composition_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            write_json(root, "config/chain.json", {"schema_version": 1, "outputs": {"manifest": "manifests/full.json"}})
            write_json(root, "manifests/full.json", {"outputs": {}})
            target = root / "work/BTL/TRICMN.BIN"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"frozen")
            write_json(root, "manifests/full-story-library-components-validation.json", {"outputs": {"BTL/TRICMN.BIN": lock(root, target)}})
            with patch.object(rebuild_zh_font, "PROJECT_ROOT", root):
                inventory = rebuild_zh_font._chain_cache_inventory({"integrated_component": "config/chain.json"})
            self.assertIn(target, inventory)

    def test_failed_upstream_proof_cannot_be_rebound_as_passed(self):
        config = {"full_story_font": {"manifest": {}, "required_status": "passed", "required_profile_id": "font"}}
        with patch.object(full, "_manifest", return_value=(Path("font.json"), {
            "status": "passed", "font_profile_id": "font", "acceptance": {"reread": False}
        })):
            with self.assertRaisesRegex(full.FullStoryComponentError, "font metadata proof failed"):
                full._validate_metadata_proofs(config)

    def test_written_atlas_corruption_is_still_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            path = root / "work/archive.bin"
            path.parent.mkdir()
            path.write_bytes(b"bad")
            with patch.object(ui_atlas, "PROJECT_ROOT", root), patch.object(ui_atlas, "WORK_ROOT", root / "work"):
                with self.assertRaisesRegex(SystemExit, "written output differs"):
                    ui_atlas._verify_written_build({"outputs": {"validation": "work/report.json"}}, {path: b"good"}, {})

    def test_reviewed_atlas_checks_hashes_without_reconstructing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            corpus = write_json(root, "corpus/atlas.json", {"text": "中"})
            component = write_json(root, "manifests/atlas.json", {"inputs": {"corpus": corpus}})
            archive_path = root / "work/suite/KURODATA/KVMDATA.BIN"
            archive_path.parent.mkdir(parents=True)
            archive_path.write_bytes(b"archive")
            archive = lock(root, archive_path)
            output = {key: archive[key] for key in ("size", "sha256")}
            suite = {"components": [{"manifest": component}],
                     "source": {"member": {"member": "KURODATA/KVMDATA.BIN"}},
                     "expected_output": output,
                     "outputs": {"component_root": "work/suite", "manifest": "manifests/suite.json"}}
            suite_lock = write_json(root, "config/suite.json", suite)
            write_json(root, "manifests/suite.json", {"inputs": {"config": suite_lock},
                                                     "acceptance": {"exact": True}, "outputs": {"archive": output}})
            write_json(root, "config/full-story-components.json", {"kvmdata": archive})
            with patch.object(text_build, "PROJECT_ROOT", root), patch.object(
                text_build, "build_ui_atlas_suite", side_effect=AssertionError("must reuse reviewed output")
            ):
                current, _ = text_build._ui_atlas_cache_is_current({"atlas_suite": "config/suite.json"})
                self.assertTrue(current)
                write_json(root, "corpus/atlas.json", {"text": "文"})
                current, reason = text_build._ui_atlas_cache_is_current({"atlas_suite": "config/suite.json"})
                self.assertFalse(current)
                self.assertIn("corpus/atlas.json", reason)

    def test_story_rebind_requires_identical_font_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            proposal = {"assignments": ["中"], "ui_selection": 1}
            original = write_json(root, "proposal.json", proposal)
            report = {"inputs": {"proposal": original},
                      "font_binary_signature": text_build._font_binary_signature(proposal)}
            report_lock = write_json(root, "story.json", report)
            stage = write_json(root, "stage.bin", {})
            hb = write_json(root, "hb.bin", {})
            write_json(root, "config/full-story-components.json", {
                "full_story_stage": {"report": report_lock, "stage": stage, "hb": hb}
            })
            proposal["ui_selection"] = 2
            write_json(root, "proposal.json", proposal)
            with patch.object(text_build, "PROJECT_ROOT", root):
                self.assertTrue(text_build._story_component_cache_is_current(set())[0])
                self.assertFalse(text_build._story_component_cache_is_current({"corpus/zh/story-dialogue/001.json"})[0])
                text_build._rebind_story_font_proposal(refresh_manifests=True)
                self.assertEqual(json.loads((root / "story.json").read_text())["inputs"]["proposal"]["sha256"],
                                 lock(root, root / "proposal.json")["sha256"])
                proposal["assignments"] = ["文"]
                write_json(root, "proposal.json", proposal)
                with self.assertRaisesRegex(text_build.TextUpdateBuildError, "mapping changed"):
                    text_build._rebind_story_font_proposal(refresh_manifests=True)


if __name__ == "__main__":
    unittest.main()
