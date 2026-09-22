import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from srwz.edition_incremental import seed_text_update
from srwz.release_inputs import sha256_file
import build_text_update_iso as pipeline


class IncrementalSeedTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.source = self.root / 'build/editions/previous/project'
        self.target = self.root / 'build/editions/next/project'
        self.source.mkdir(parents=True);self.target.mkdir(parents=True)
        self.write('build/editions/previous/project/config/derived.json', {'generated': True})
        p = self.source / 'config/derived.json'
        self.write('build/editions/previous/project/work/cache/editions/original/font-chain.json',
                   {'files': [{'path':'config/derived.json','size':p.stat().st_size,'sha256':sha256_file(p)}]})
        self.write('build/editions/previous/project/manifests/proof.json', {'passed':True})
        self.files = [{'path':'config/derived.json','sha256':'source-definition'}, {'path':'corpus/line.json','sha256':'before'},
                      {'path':'tools/compiler.py','sha256':'compiler'}]
        self.write('work/build/shared/old/inputs.json', {'files':self.files})
        self.write('manifests/editions/original/current.json', {'status':'edition_iso_static_validated_runtime_pending',
            'input_digest':'old','edition_contract_sha256':'contract','workspace':'build/editions/previous/project',
            'readback':{'path':'build/editions/previous/project/manifests/proof.json','sha256':sha256_file(self.source/'manifests/proof.json')}})
        self.context = SimpleNamespace(root=self.root,project_root=self.target,receipt=self.root/'manifests/editions/original/current.json',
                                       profile=SimpleNamespace(contract_sha256='contract'))

    def write(self, path, value):
        p=self.root/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value))

    def test_corpus_only_edit_seeds_generated_metadata_without_mutating_old_run(self):
        rows=[dict(r,sha256='after') if r['path'].startswith('corpus/') else r for r in self.files]
        with patch('srwz.edition_incremental.seed_original_caches') as seed:
            self.assertTrue(seed_text_update(self.context, SimpleNamespace(files=rows)))
        seed.assert_called_once_with(self.source,self.target,overwrite_cache=True)
        self.assertEqual((self.source/'config/derived.json').read_bytes(),(self.target/'config/derived.json').read_bytes())
        self.assertNotEqual((self.source/'config/derived.json').stat().st_ino,(self.target/'config/derived.json').stat().st_ino)

    def test_tool_or_config_edit_cannot_reuse_old_generated_config(self):
        for name in ('tools/compiler.py','config/derived.json'):
            rows=[dict(r,sha256='changed') if r['path']==name else r for r in self.files]
            self.assertFalse(seed_text_update(self.context,SimpleNamespace(files=rows)))
        self.assertFalse((self.target/'config').exists())

    def test_corrupt_generated_metadata_rejects_seed(self):
        (self.source/'config/derived.json').write_text('{}')
        self.assertFalse(seed_text_update(self.context,SimpleNamespace(files=self.files)))

    def test_post_component_iso_lock_refresh_does_not_discard_text_cache(self):
        name = 'config/iso/zh-release-current-build.json'
        self.write('build/editions/previous/project/' + name, {'expected_sha256':'before-iso'})
        path = self.source / name
        cache_path = self.source / 'work/cache/editions/original/font-chain.json'
        cache = json.loads(cache_path.read_text())
        cache['files'].append({'path':name,'size':path.stat().st_size,'sha256':sha256_file(path)})
        cache_path.write_text(json.dumps(cache))
        path.write_text(json.dumps({'expected_sha256':'after-iso'}))
        self.files.append({'path':name,'sha256':'unchanged-source-config'})
        self.write('work/build/shared/old/inputs.json', {'files':self.files})
        self.write('build/editions/next/project/' + name, {'captured':'source-config'})
        with patch('srwz.edition_incremental.seed_original_caches'):
            self.assertTrue(seed_text_update(self.context,SimpleNamespace(files=self.files)))
        self.assertEqual(json.loads((self.target/name).read_text()),{'captured':'source-config'})

    def test_private_pipeline_uses_frozen_inventory_instead_of_parent_git(self):
        self.write('work/edition-inputs.json', {'source_head':'captured','input_digest':'digest',
            'paths':['config/main.json','config/products/special-disc/example.json','corpus/line.json']})
        with patch.object(pipeline,'PROJECT_ROOT',self.root), patch.object(pipeline.subprocess,'run',side_effect=AssertionError('parent Git read')):
            self.assertEqual(pipeline._git_state()['head'],'captured')
            self.assertEqual(pipeline._tracked_config_paths(),(self.root/'config/main.json',))
            self.write('corpus/unexpected.json',{})
            with self.assertRaisesRegex(pipeline.TextUpdateBuildError,'outside frozen inputs'):
                pipeline._assert_no_untracked_production_json()

    def test_text_dependency_refresh_keeps_full_build_snapshot_reference_format(self):
        self.write('snapshot.json', {'snapshot_id':'font-v1','primary_mapping_sha256':'primary'})
        self.write('proposal.json', {'assignments':[]})
        def lock(name):
            p=self.root/name
            return {'path':name,'size':p.stat().st_size,'sha256':sha256_file(p)}
        self.write('manifest.json', {'proposal':lock('proposal.json'),'inputs':{'allocation_snapshot':lock('snapshot.json')}})
        self.write('component.bin', {})
        compatibility = {'release_snapshot':{'path':'snapshot.json','sha256':lock('snapshot.json')['sha256'],'snapshot_id':'font-v1'},
            'release_snapshot_primary_mapping_sha256':'primary','release_assignment_count':0,
            'release_assignment_mapping_sha256':pipeline._assignment_mapping_sha256([])}
        component = lock('component.bin')
        config = {'full_story_font':{'manifest':lock('manifest.json'),'slps':component,'vt1':component},
            'full_story_stage':{'report':component,'stage':component,'hb':component},
            'runtime_keywords':{'library_archive':component,'library_component_manifest':component},
            'remaining_ui':{'stage_default_formation_inventory':component},
            'composition':{'release_codebook':compatibility}}
        self.write('config/full-story-components.json', config)
        with patch.object(pipeline,'PROJECT_ROOT',self.root):
            pipeline._update_full_component_dependencies(refresh=False)
        self.assertEqual(json.loads((self.root/'config/full-story-components.json').read_text())['composition']['release_codebook'],compatibility)
