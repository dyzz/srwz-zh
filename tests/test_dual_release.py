"""Reject cross-edition patches and stale final readbacks before encoding."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import build_release as release


class DualReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.root_patch = patch.object(release, "PROJECT_ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.config = {"schema_version": 2, "version": "0.4.0", "tag": "v0.4.0",
                       "output": {"directory": "build/release/v0.4.0"},
                       "validation": "manifests/release/v0.4.0.json", "editions": {}}
        self.validation = {"status": "dual_edition_build_and_static_readback_passed",
                           "verification": {"both_editions": True,
                                            "status": "edition_batch_receipt_integrity_passed"},
                           "outputs": {}, "readbacks": {}, "input_digest": "batch-one"}
        for number, edition in enumerate(("original", "best"), 1):
            source = {"path": f"rom/{edition}.iso", "size": 100 + number, "sha256": str(number) * 64}
            target = {"path": f"build/iso/v0.4.0/srwz-zh-v0.4.0-{edition}.iso",
                      "size": 100 + number, "sha256": str(number + 2) * 64}
            contract_path = f"config/editions/{edition}/edition.json"
            self.write(contract_path, {"edition_id": edition, "source_iso": source})
            self.config["editions"][edition] = {"edition_config": contract_path, "source_iso": source,
                                               "target_iso": target,
                                               "patch_filename": f"srwz-zh-v0.4.0-{edition}.xdelta"}
            status = ("full_story_final_iso_static_content_readback_passed" if edition == "original"
                      else "best_final_iso_static_content_readback_passed")
            proof_path = f"manifests/release/{edition}.json"
            self.write(proof_path, {"status": status, "iso": target, "input_digest": "batch-one"})
            proof = self.root / proof_path
            self.validation["outputs"][edition] = target
            self.validation["readbacks"][edition] = {"path": proof_path, "size": proof.stat().st_size,
                                                       "sha256": release.sha256_file(proof)}
        self.write(self.config["validation"], self.validation)

    def write(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_accepts_two_independently_bound_editions(self):
        self.assertEqual(release.verify_dual_config_bindings(self.config), self.validation)

    def add_skip_variants(self):
        self.config.update(schema_version=3, default_variant='no-skip')
        self.validation['variants'] = {}
        for edition, item in self.config['editions'].items():
            target = {**item['target_iso'],
                      'path': item['target_iso']['path'].replace('.iso', '-skip.iso'),
                      'sha256': ('a' if edition == 'original' else 'b') * 64}
            item['skip_variant'] = {'target_iso': target,
                                    'patch_filename': item['patch_filename'].replace('.xdelta', '-skip.xdelta')}
            path = f'manifests/release/{edition}-skip.json'
            self.write(path, {'status': 'skip_variant_exact_transform_readback_passed',
                             'edition': edition, 'base_sha256': item['target_iso']['sha256'],
                             'size': target['size'], 'sha256': target['sha256'],
                             'only_declared_skip_changes': True})
            self.validation['variants'][edition] = {'target_iso': target, 'readback': {
                'path': path, 'size': (self.root/path).stat().st_size,
                'sha256': release.sha256_file(self.root/path)}}
        self.write(self.config['validation'], self.validation)

    def test_four_variants_each_use_the_corresponding_japanese_source(self):
        self.add_skip_variants()
        release.verify_dual_config_bindings(self.config)
        targets = dict(release.release_targets(self.config))
        self.assertEqual(set(targets), {'original', 'original-skip', 'best', 'best-skip'})
        for edition in ('original', 'best'):
            self.assertEqual(targets[edition]['source_iso'], targets[edition+'-skip']['source_iso'])
            self.assertNotEqual(targets[edition]['target_iso'], targets[edition+'-skip']['target_iso'])

    def test_skip_variant_cannot_use_another_base_or_stale_receipt(self):
        self.add_skip_variants()
        path = self.root/'manifests/release/best-skip.json'
        proof = json.loads(path.read_text())
        proof['base_sha256'] = self.config['editions']['original']['target_iso']['sha256']
        self.write(str(path.relative_to(self.root)), proof)
        lock = self.validation['variants']['best']['readback']
        lock.update(size=path.stat().st_size, sha256=release.sha256_file(path))
        self.write(self.config['validation'], self.validation)
        with self.assertRaisesRegex(release.ReleaseBuildError, 'skip readback mismatch'):
            release.verify_dual_config_bindings(self.config)

    def test_four_variant_release_rejects_missing_variant(self):
        self.add_skip_variants()
        del self.config['editions']['best']['skip_variant']
        with self.assertRaisesRegex(release.ReleaseBuildError, 'skip variant binding mismatch'):
            release.verify_dual_config_bindings(self.config)

    def add_built_in_skip(self):
        self.config.update(schema_version=4, skip='built_in')
        self.validation.update(status='edition_build_and_static_readback_passed',
                               skip='built_in', skip_readbacks={})
        self.validation['verification']['verified_editions'] = ['original', 'best', 'sp']
        source = {'path': 'rom/sp.iso', 'size': 200, 'sha256': 'a' * 64}
        target = {'path': 'build/iso/v0.4.0/srwz-zh-v0.4.0-sp.iso', 'size': 200, 'sha256': 'b' * 64}
        contract = 'config/editions/sp/edition.json'
        self.write(contract, {'edition_id': 'sp', 'source_iso': source})
        self.config['editions']['sp'] = {'edition_config': contract, 'source_iso': source,
                                       'target_iso': target, 'patch_filename': 'srwz-zh-v0.4.0-sp.xdelta'}
        independent_path = 'manifests/release/sp-independent.json'
        self.write(independent_path, {'status': 'all_bound_text_reread_from_final_iso', 'iso': target,
                                      'component_hashes_verified': True})
        independent = self.root / independent_path
        independent_lock = {'path': independent_path, 'size': independent.stat().st_size,
                            'sha256': release.sha256_file(independent)}
        proof_path = 'manifests/release/sp.json'
        self.write(proof_path, {'status': 'all_bound_text_reread_from_final_iso_runtime_pending',
                               'iso': target, 'independent_readback': independent_lock,
                               'coverage': {'pending_targets': [], 'unassigned_display_characters': []}})
        proof = self.root / proof_path
        self.validation['outputs']['sp'] = target
        self.validation['readbacks']['sp'] = {'path': proof_path, 'size': proof.stat().st_size,
                                             'sha256': release.sha256_file(proof)}
        self.validation['sp_independent_readback'] = independent_lock
        for edition, item in self.config['editions'].items():
            path = f'manifests/release/{edition}-skip.json'
            self.write(path, {'status': 'built_in_skip_hook_readback_passed', 'edition': edition,
                              'iso': item['target_iso'], 'skip_enabled': True})
            proof = self.root / path
            self.validation['skip_readbacks'][edition] = {'path': path, 'size': proof.stat().st_size,
                                                         'sha256': release.sha256_file(proof)}
        self.write(self.config['validation'], self.validation)

    def test_built_in_skip_release_has_one_patch_per_edition(self):
        self.add_built_in_skip()
        self.assertEqual(release.verify_dual_config_bindings(self.config), self.validation)
        targets = dict(release.release_targets(self.config))
        self.assertEqual(set(targets), {'original', 'best', 'sp'})
        self.assertEqual(targets['best']['patch_filename'], 'srwz-zh-v0.4.0-best.xdelta')
        self.assertEqual(targets['sp']['patch_filename'], 'srwz-zh-v0.4.0-sp.xdelta')

    def test_current_release_rejects_missing_sp_or_unverified_sp(self):
        self.add_built_in_skip()
        config = copy.deepcopy(self.config)
        del config['editions']['sp']
        with self.assertRaisesRegex(release.ReleaseBuildError, 'exactly original, best and sp'):
            release.verify_dual_config_bindings(config)
        self.validation['verification']['verified_editions'].remove('sp')
        self.write(self.config['validation'], self.validation)
        with self.assertRaisesRegex(release.ReleaseBuildError, 'verification must include'):
            release.verify_dual_config_bindings(self.config)

    def test_sp_rejects_wrong_source_missing_hook_or_independent_proof(self):
        self.add_built_in_skip()
        config = copy.deepcopy(self.config)
        config['editions']['sp']['source_iso'] = config['editions']['original']['source_iso']
        with self.assertRaisesRegex(release.ReleaseBuildError, 'sp: source ISO'):
            release.verify_dual_config_bindings(config)
        del self.validation['skip_readbacks']['sp']
        self.write(self.config['validation'], self.validation)
        with self.assertRaisesRegex(release.ReleaseBuildError, 'skip hook proof is required'):
            release.verify_dual_config_bindings(self.config)
        self.add_built_in_skip()
        del self.validation['sp_independent_readback']
        self.write(self.config['validation'], self.validation)
        with self.assertRaisesRegex(release.ReleaseBuildError, 'SP independent readback'):
            release.verify_dual_config_bindings(self.config)

    def test_sp_rejects_rebound_independent_proof_for_other_iso(self):
        self.add_built_in_skip()
        independent = self.validation['sp_independent_readback']
        self.write(independent['path'], {'status': 'all_bound_text_reread_from_final_iso',
                                        'iso': self.config['editions']['best']['target_iso'],
                                        'component_hashes_verified': True})
        path = self.root / independent['path']
        independent.update(size=path.stat().st_size, sha256=release.sha256_file(path))
        lock = self.validation['readbacks']['sp']
        proof = json.loads((self.root / lock['path']).read_text())
        proof['independent_readback'] = independent
        self.write(lock['path'], proof)
        path = self.root / lock['path']
        lock.update(size=path.stat().st_size, sha256=release.sha256_file(path))
        self.write(self.config['validation'], self.validation)
        with self.assertRaisesRegex(release.ReleaseBuildError, 'SP independent readback or coverage mismatch'):
            release.verify_dual_config_bindings(self.config)

    def test_sp_rejects_incomplete_corpus_or_font_coverage(self):
        for field in ('pending_targets', 'unassigned_display_characters'):
            with self.subTest(field=field):
                self.add_built_in_skip()
                lock = self.validation['readbacks']['sp']
                path = self.root / lock['path']
                proof = json.loads(path.read_text())
                proof['coverage'][field] = ['missing']
                self.write(lock['path'], proof)
                lock.update(size=path.stat().st_size, sha256=release.sha256_file(path))
                self.write(self.config['validation'], self.validation)
                with self.assertRaisesRegex(release.ReleaseBuildError, 'coverage mismatch'):
                    release.verify_dual_config_bindings(self.config)

    def test_built_in_skip_release_requires_hook_proof_for_each_target(self):
        self.add_built_in_skip()
        del self.validation['skip_readbacks']['best']
        self.write(self.config['validation'], self.validation)
        with self.assertRaisesRegex(release.ReleaseBuildError, 'skip hook proof is required'):
            release.verify_dual_config_bindings(self.config)
        self.add_built_in_skip()
        self.write('manifests/release/best-skip.json', {'status': 'built_in_skip_hook_readback_passed', 'edition': 'best',
                   'iso': self.config['editions']['original']['target_iso'], 'skip_enabled': True})
        with self.assertRaisesRegex(release.ReleaseBuildError, 'skip hook proof'):
            release.verify_dual_config_bindings(self.config)
        self.add_built_in_skip()
        self.config['editions']['best']['skip_variant'] = {'patch_filename': 'x'}
        with self.assertRaisesRegex(release.ReleaseBuildError, 'no separate skip variant'):
            release.verify_dual_config_bindings(self.config)
        del self.config['editions']['best']['skip_variant']
        self.config['skip'] = 'optional'
        with self.assertRaisesRegex(release.ReleaseBuildError, 'skip built into every target'):
            release.verify_dual_config_bindings(self.config)

    def test_rejects_best_patch_with_original_source(self):
        config = copy.deepcopy(self.config)
        config["editions"]["best"]["source_iso"] = config["editions"]["original"]["source_iso"]
        with self.assertRaisesRegex(release.ReleaseBuildError, "source ISO"):
            release.verify_dual_config_bindings(config)

    def test_rejects_stale_target_even_if_named_correctly(self):
        config = copy.deepcopy(self.config)
        config["editions"]["best"]["target_iso"]["sha256"] = "f" * 64
        with self.assertRaisesRegex(release.ReleaseBuildError, "final validation"):
            release.verify_dual_config_bindings(config)

    def test_rejects_renamed_patch(self):
        config = copy.deepcopy(self.config)
        config["editions"]["best"]["patch_filename"] = "srwz-zh-v0.4.0-original.xdelta"
        with self.assertRaisesRegex(release.ReleaseBuildError, "filename"):
            release.verify_dual_config_bindings(config)

    def test_rejects_modified_readback(self):
        self.write("manifests/release/best.json", {"status": "passed"})
        with self.assertRaisesRegex(release.ReleaseBuildError, "readback"):
            release.verify_dual_config_bindings(self.config)

    def test_rejects_missing_edition(self):
        del self.config["editions"]["best"]
        with self.assertRaisesRegex(release.ReleaseBuildError, "exactly original and best"):
            release.verify_dual_config_bindings(self.config)

    def test_rejects_best_proof_from_other_batch(self):
        self.validation["input_digest"] = "batch-two"
        self.write(self.config["validation"], self.validation)
        with self.assertRaisesRegex(release.ReleaseBuildError, "different input batch"):
            release.verify_dual_config_bindings(self.config)


if __name__ == "__main__":
    unittest.main()
