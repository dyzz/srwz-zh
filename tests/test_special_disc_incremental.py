"""SP cache invalidation, corruption recovery and publication boundaries."""
import copy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from special_disc.writeback.incremental import (
    CACHE_PATH, COMPONENTS, ComponentCache, component_inputs, file_lock, seed_components,
)
from srwz.edition import json_bytes, load_json
from srwz.release_inputs import copy_file, sha256_file


class SpIncrementalTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.work = self.root / 'work/build/special-disc/full-text/runs/first'
        self.rows = [dict(path=p, size=1, sha256=hashlib.sha256(p.encode()).hexdigest()) for p in (
            'tools/srwz/codec.py', 'tools/special_disc/writeback/write_system_text.py',
            'config/fonts/test.json', 'work/build/special-disc/text-candidate/font/proposal.json',
            'corpus/zh/special-disc/system-text.json', 'corpus/zh/special-disc/frame-text.json',
            'corpus/zh/special-disc/story-dialogue.json', 'corpus/zh/special-disc/battle-lines.json',
            'corpus/zh/story-dialogue/stage-001.json', 'corpus/zh/battle/srvc-lines.json',
            'corpus/zh/menu/stage-names.json', 'corpus/zh/library/unused.json', 'tools/build_release.py')]
        self.calls = []

    def builder(self, work, name, value=None):
        def run():
            self.calls.append(name)
            # The system writer hands STAGE to the stage writer as a decoded overlay.
            member = 'DATA/STAGE.BIN.overlay' if name == 'system' else 'DATA/STAGE.BIN'
            path = work / name / member
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(value or name.encode())
            status = 'static_component_verified_runtime_pending' if name == 'stage' else 'static_verified_runtime_pending'
            (work / name / 'report.json').write_bytes(json_bytes({
                'status': status, 'files': {member: sha256_file(path)},
                'baseline': {'path': str(work / 'system')}, 'proposal': {'path': 'old'}}))
        return run

    def warm(self):
        cache = ComponentCache(self.root, self.work, rows=self.rows)
        for name in COMPONENTS:
            cache.run(name, self.builder(self.work, name))
        receipt = cache.receipt()
        directory = self.root / CACHE_PATH
        directory.mkdir(parents=True, exist_ok=True)
        for row in receipt['components'].values():
            for lock in [row['report'], *row['files']]:
                copy_file(self.work / lock['path'], directory / lock['path'])
        (directory / 'cache.json').write_bytes(json_bytes(receipt))
        self.calls.clear()
        return receipt

    def update(self, rows=None, force=False, system_value=None):
        work = self.root / 'work/build/special-disc/full-text/runs/next'
        cache = ComponentCache(self.root, work, rows=rows or self.rows, force=force)
        for name in COMPONENTS:
            cache.run(name, self.builder(work, name, system_value if name == 'system' else None))
        return cache.receipt()

    def test_corpus_dependency_matrix_and_additions_removals(self):
        cases = {
            'corpus/zh/story-dialogue/stage-001.json': {'stage'},
            'corpus/zh/special-disc/battle-lines.json': {'srvc'},
            'corpus/zh/menu/stage-names.json': {'frame'},
            'corpus/zh/special-disc/frame-text.json': {'system', 'stage', 'frame', 'image-labels'},
            'corpus/zh/library/unused.json': set(), 'tools/build_release.py': set(),
            'config/fonts/test.json': set(COMPONENTS), 'tools/srwz/codec.py': set(COMPONENTS),
        }
        for path, affected in cases.items():
            for mutation in ('edit', 'delete', 'add'):
                rows = copy.deepcopy(self.rows)
                row = next(r for r in rows if r['path'] == path)
                if mutation == 'edit': row['sha256'] = 'f' * 64
                elif mutation == 'delete': rows.remove(row)
                else: rows.append({**row, 'path': path.replace('.json', '-new.json').replace('.py', '-new.py')})
                actual = {name for name in COMPONENTS if component_inputs(rows, name) != component_inputs(self.rows, name)}
                # New unrelated sibling files are ignored unless a whole input directory is consumed.
                if mutation == 'add' and path in ('corpus/zh/special-disc/battle-lines.json',
                                                 'corpus/zh/menu/stage-names.json',
                                                 'corpus/zh/special-disc/frame-text.json'):
                    affected_now = set()
                else: affected_now = affected
                with self.subTest(path=path, mutation=mutation): self.assertEqual(actual, affected_now)

    def test_unchanged_components_reuse_and_force_rebuilds(self):
        self.warm()
        result = self.update()
        self.assertEqual(self.calls, [])
        self.assertTrue(all(r['mode'] == 'reused' for r in result['components'].values()))
        self.update(force=True)
        self.assertEqual(self.calls, list(COMPONENTS))

    def test_system_changed_bytes_invalidate_stage_but_not_other_components(self):
        self.warm()
        rows = copy.deepcopy(self.rows)
        next(r for r in rows if r['path'].endswith('/system-text.json'))['sha256'] = 'e' * 64
        result = self.update(rows, system_value=b'changed STAGE baseline')
        self.assertEqual(self.calls, ['system', 'stage'])
        self.assertEqual(result['components']['srvc']['mode'], 'reused')

    def test_system_metadata_change_with_same_stage_bytes_reuses_stage(self):
        self.warm()
        rows = copy.deepcopy(self.rows)
        next(r for r in rows if r['path'].endswith('/system-text.json'))['sha256'] = 'e' * 64
        self.update(rows)
        self.assertEqual(self.calls, ['system'])

    def test_corrupt_or_missing_cached_bytes_rebuild_only_affected_writer(self):
        self.warm()
        (self.root / CACHE_PATH / 'srvc/DATA/STAGE.BIN').write_bytes(b'corrupt')
        (self.root / CACHE_PATH / 'image-labels/report.json').unlink()
        self.update()
        self.assertEqual(self.calls, ['srvc', 'image-labels'])

    def test_failed_or_unsealed_generation_cannot_seed(self):
        receipt = self.warm()
        independent = self.work / 'independent-readback.json'
        iso = dict(path='build/iso/special-disc/sp-current.iso', size=100, sha256='a' * 64)
        independent.write_bytes(json_bytes(dict(status='all_bound_text_reread_from_final_iso',
                                                iso=iso, component_hashes_verified=True)))
        report = dict(status='all_bound_text_reread_from_final_iso_runtime_pending', incremental=receipt,
                      iso=iso, independent_readback=file_lock(independent, self.root),
                      components={str((self.work / n / 'report.json').relative_to(self.root)):
                                  receipt['components'][n]['report']['sha256'] for n in COMPONENTS})
        manifest = self.root / 'sp.json'
        manifest.write_bytes(json_bytes(report))
        target = self.root / 'seed'
        self.assertTrue(seed_components(self.root, manifest, sha256_file(manifest), target))
        self.assertEqual(load_json(target / 'cache.json'), receipt)
        self.assertFalse(seed_components(self.root, manifest, '0' * 64, self.root / 'bad-hash'))
        report['status'] = 'failed'; manifest.write_bytes(json_bytes(report))
        self.assertFalse(seed_components(self.root, manifest, sha256_file(manifest), self.root / 'failed'))
        report['status'] = 'all_bound_text_reread_from_final_iso_runtime_pending'
        manifest.write_bytes(json_bytes(report)); independent.write_bytes(b'{}')
        self.assertFalse(seed_components(self.root, manifest, sha256_file(manifest), self.root / 'bad-proof'))

    def test_inputs_changing_during_build_cannot_be_sealed(self):
        changed = copy.deepcopy(self.rows)
        changed[0]['sha256'] = 'f' * 64
        with patch('special_disc.writeback.incremental.locked_sp_inputs', return_value=()), \
                patch('special_disc.writeback.incremental.source_inventory', side_effect=[self.rows, changed]):
            cache = ComponentCache(self.root, self.work)
            for name in COMPONENTS:
                cache.run(name, self.builder(self.work, name))
            with self.assertRaisesRegex(ValueError, 'inputs changed during component build'):
                cache.receipt()


if __name__ == '__main__':
    unittest.main()
