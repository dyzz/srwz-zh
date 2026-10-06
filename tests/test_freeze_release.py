"""Freezing a verified batch yields a schema 4 release with hook proofs, never variants."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import freeze_release
import build_release


class FreezeReleaseTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        root_patch = patch.object(freeze_release, 'ROOT', self.root);root_patch.start();self.addCleanup(root_patch.stop)
        results = []
        for edition in freeze_release.RELEASE_EDITIONS:
            iso = self.write_bytes(f'build/iso/zh-release-{edition}/current-{edition}.iso', edition.encode() * 4096)
            output = freeze_release.lock(iso)
            status = {'original': 'full_story_final_iso_static_content_readback_passed',
                      'best': 'best_final_iso_static_content_readback_passed',
                      'sp': 'all_bound_text_reread_from_final_iso_runtime_pending'}[edition]
            data = {'status': status, 'iso': output, 'input_digest': 'digest'}
            if edition == 'sp':
                independent = self.write_json('build/editions/sp/independent.json', {
                    'status': 'all_bound_text_reread_from_final_iso', 'iso': output,
                    'component_hashes_verified': True})
                data.update(coverage={'pending_targets': [], 'unassigned_display_characters': []},
                            independent_readback={'path': 'independent.json',
                                                  'sha256': freeze_release.sha256_file(independent)})
            proof = self.write_json(f'build/editions/{edition}/proof.json', data)
            source = self.write_bytes(f'rom/{edition}.iso', b'japanese-' + edition.encode() * 4096)
            self.write_json(f'config/editions/{edition}/edition.json', {'edition_id': edition,
                            'source_iso': freeze_release.lock(source)})
            results.append({'edition_id': edition, 'workspace': f'build/editions/{edition}',
                            'output': output,
                            'readback': {'path': str(proof.relative_to(self.root))}})
        # Freeze validates the title badge from the captured build inputs.
        self.badge_path = self.write_json(
            'work/build/shared/digest/project/config/assets/title-menu-zh.json',
            {'version_badge': {'text': 'v0.5.0'}})
        self.batch = self.write_json('work/editions/digest/original-best-sp.json', {
            'input_digest': 'digest', 'input_snapshot': 'work/build/shared/digest/inputs.json', 'results': results})
        self.verification = {'both_editions': True, 'verified_editions': ['original', 'best', 'sp'],
                             'status': 'edition_batch_receipt_integrity_passed'}

    def write_bytes(self, name, data):
        path = self.root / name;path.parent.mkdir(parents=True, exist_ok=True);path.write_bytes(data);return path

    def write_json(self, name, value):
        return self.write_bytes(name, json.dumps(value).encode())

    def test_freeze_writes_built_in_skip_release_bound_to_hook_proofs(self):
        hooks = []
        def verify_skip(path, inputs, edition):
            hooks.append((path.name, inputs.name, edition));return {'hook': edition}
        with patch.object(freeze_release, 'verify_batch', return_value=self.verification), \
                patch.object(freeze_release, 'verify_skip', side_effect=verify_skip):
            config_path = freeze_release.freeze(self.batch, '0.5.0', xdelta={'executable': 'xdelta3'})
        config = json.loads(config_path.read_text())
        self.assertEqual((config['schema_version'], config['skip']), (4, 'built_in'))
        self.assertEqual(sorted(hooks), [('srwz-zh-v0.5.0-best.iso', 'project', 'best'),
                                         ('srwz-zh-v0.5.0-original.iso', 'project', 'original'),
                                         ('srwz-zh-v0.5.0-sp.iso', 'project', 'sp')])
        for edition, item in config['editions'].items():
            self.assertNotIn('skip_variant', item)
            self.assertEqual(item['patch_filename'], f'srwz-zh-v0.5.0-{edition}.xdelta')
            self.assertEqual(item['target_iso']['path'], f'build/iso/v0.5.0/srwz-zh-v0.5.0-{edition}.iso')
        validation = json.loads((self.root / config['validation']).read_text())
        self.assertEqual(validation['skip'], 'built_in')
        for edition in freeze_release.RELEASE_EDITIONS:
            proof = json.loads((self.root / validation['skip_readbacks'][edition]['path']).read_text())
            self.assertEqual(proof['status'], 'built_in_skip_hook_readback_passed')
            self.assertEqual(proof['iso'], validation['outputs'][edition])
        self.assertEqual(sorted(p.name for p in (self.root / 'build/iso/v0.5.0').iterdir()),
                         ['srwz-zh-v0.5.0-best.iso', 'srwz-zh-v0.5.0-original.iso', 'srwz-zh-v0.5.0-sp.iso'])
        # Publication must remain verifiable after the private SP workspace is removed.
        shutil.rmtree(self.root / 'build/editions/sp')
        with patch.object(build_release, 'PROJECT_ROOT', self.root):
            self.assertEqual(build_release.verify_dual_config_bindings(config), validation)
        with self.assertRaisesRegex(ValueError, 'release already exists'), \
                patch.object(freeze_release, 'verify_batch', return_value=self.verification):
            freeze_release.freeze(self.batch, '0.5.0', xdelta={})

    def test_badge_failures_do_not_fall_back_to_mutable_config_or_create_release(self):
        self.write_json('config/assets/title-menu-zh.json',
                        {'version_badge': {'text': 'v0.5.0'}})
        for badge, error, message in (
            (None, FileNotFoundError, 'title-menu-zh.json'),
            ('v0.4.2', ValueError, 'rebuild with --release-version 0.5.0'),
            ('v0.5.0+20261006', ValueError, 'rebuild with --release-version 0.5.0'),
        ):
            with self.subTest(frozen_badge=badge):
                if badge is None:
                    self.badge_path.unlink()
                else:
                    self.badge_path.write_text(json.dumps({'version_badge': {'text': badge}}))
                with patch.object(freeze_release, 'verify_batch', return_value=self.verification), \
                        self.assertRaisesRegex(error, message):
                    freeze_release.freeze(self.batch, '0.5.0', xdelta={})
                for path in ('build/iso/v0.5.0', 'manifests/releases/v0.5.0',
                             'config/release/v0.5.0.json'):
                    self.assertFalse((self.root / path).exists(), path)

    def test_freeze_requires_all_three_editions(self):
        for missing in freeze_release.RELEASE_EDITIONS:
            verification = {**self.verification,
                            'verified_editions': [e for e in freeze_release.RELEASE_EDITIONS if e != missing]}
            with self.subTest(missing=missing), \
                    patch.object(freeze_release, 'verify_batch', return_value=verification):
                with self.assertRaisesRegex(ValueError, 'requires original, best and sp'):
                    freeze_release.freeze(self.batch, '0.5.0', xdelta={})
        self.assertFalse((self.root / 'build/iso/v0.5.0').exists())

    @unittest.skipUnless(shutil.which('xdelta3'), 'xdelta3 is needed for patch roundtrip')
    def test_frozen_three_edition_release_encodes_and_reconstructs_every_patch(self):
        xdelta = {'executable': 'xdelta3', 'version_line': build_release.xdelta_version('xdelta3'),
                  'encode_args': ['-e', '-9']}
        with patch.object(freeze_release, 'verify_batch', return_value=self.verification), \
                patch.object(freeze_release, 'verify_skip', return_value={}):
            config_path = freeze_release.freeze(self.batch, '0.5.0', xdelta=xdelta)
        config = json.loads(config_path.read_text())
        for path in config['evidence']:
            if not (self.root / path).exists():
                self.write_bytes(path, b'test evidence')
        with patch.object(build_release, 'PROJECT_ROOT', self.root), \
                patch.object(build_release, 'verify_built_in_skip', return_value={}) as hooks:
            output = build_release.build_release(config_path)
        manifest = json.loads((output / 'release-manifest.json').read_text())
        self.assertEqual(set(manifest['patches']), {'original', 'best', 'sp'})
        self.assertEqual([call.args[1] for call in hooks.call_args_list], ['best', 'original', 'sp'])
        for edition, item in manifest['patches'].items():
            self.assertTrue(item['reconstructed_size_matches'])
            self.assertTrue(item['reconstructed_sha256_matches'])
            self.assertEqual(item['source_iso']['path'], f'rom/{edition}.iso')
        self.assertEqual(len(list(output.glob('*.xdelta'))), 3)
        self.assertFalse(list(output.glob('*.iso')))
        self.assertIn('Original、The Best 和 SP 三份补丁', (output / 'README.txt').read_text())


if __name__ == '__main__':
    unittest.main()
