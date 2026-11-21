import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/zh_hant'))
sys.path.insert(0, str(ROOT / 'tools'))
import fill_corpora
from srwz.release_inputs import SOURCE_ROOTS, source_inventory


class RegionalCorpusTests(unittest.TestCase):
    def test_coverage_check_reports_missing_text_and_writes_nothing(self):
        import sync_corpus
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / 'corpus/zh/stage.json'
            tw = root / 'corpus/zh-hant/stage.json'
            hk = root / 'corpus/zh-hant-hk/stage.json'
            for f in (src, tw, hk):
                f.parent.mkdir(parents=True)
            src.write_text(json.dumps({'entries': [{'id': 'a', 'translation': '出发'}, {'id': 'b', 'translation': '机体'}]}))
            tw.write_text(json.dumps({'entries': [{'id': 'a', 'translation': '出發'}]}))
            hk.write_text(json.dumps({'entries': [{'id': 'a', 'translation': '出發'}, {'id': 'b', 'translation': '機體'}]}))
            before = (tw.read_bytes(), hk.read_bytes())
            with patch.object(sync_corpus, 'ROOT', root):
                with self.assertRaises(SystemExit) as stop:
                    fill_corpora.prepare(root)
            self.assertIn('corpus/zh-hant/stage.json', str(stop.exception))
            self.assertNotIn('zh-hant-hk', str(stop.exception))
            self.assertEqual(before, (tw.read_bytes(), hk.read_bytes()))

    def test_missing_terrain_name_matches_the_japanese_source(self):
        source = [{'source': '甲', 'translation': '第一'}, {'source': '乙', 'translation': '第二'}]
        existing = [{'source': '乙', 'translation': '人工譯文'}]
        self.assertFalse(fill_corpora.covers(source, existing))
        self.assertTrue(fill_corpora.covers(source, [source[0], existing[0]]))

    def test_missing_regional_file_cannot_ship_the_simplified_wording(self):
        from build_dual import overlay_tree
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src, dst = root / 'hk', root / 'private/corpus/zh'
            src.mkdir()
            dst.mkdir(parents=True)
            (dst / 'menu.json').write_text('{"name": "简体"}')
            with self.assertRaisesRegex(ValueError, 'menu.json'):
                overlay_tree(src, dst)

    def test_hong_kong_stage_and_terrain_text_are_not_shared_picture_inputs(self):
        from build_dual import hk_uses_taiwan
        for name in ('menu/stage-names.json', 'menu/mapmodel-terrain-names.json'):
            self.assertNotIn(name, hk_uses_taiwan())
            self.assertTrue((ROOT / 'corpus/zh-hant-hk' / name).is_file())

    def test_sp_shared_title_art_preserves_hong_kong_text(self):
        import build_dual_sp
        from special_disc.writeback import stage_titles

        def rows(tree):
            doc = json.loads((ROOT / 'corpus' / tree / 'special-disc/frame-text.json').read_text())
            return {row['id']: row for row in doc['entries']}

        tw, hk = rows('zh-hant'), rows('zh-hant-hk')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus = root / 'corpus/zh/special-disc/frame-text.json'
            corpus.parent.mkdir(parents=True)
            hk['episode-title/013']['translation'] = '香港章節測試'
            hk['vt1-page/006']['translation'] = '香港任務測試'
            corpus.write_text(json.dumps({'entries': list(hk.values())}))
            build_dual_sp.sp_shared_pictures(root)
            output = {r['id']: r for r in json.loads(corpus.read_text())['entries']}
            for key, row in hk.items():
                expected = tw[key] if row['category'] == 'image-label' else row
                self.assertEqual(output[key]['translation'], expected['translation'], key)
            snapshot = root / 'config/assets/special-disc/stage-title-graphics.json'
            with patch.object(stage_titles, 'SNAPSHOT', snapshot), patch.object(stage_titles, 'CORPUS', corpus):
                picture = stage_titles.title_entries()['episode-title/013']
            self.assertEqual(picture['translation'], tw['episode-title/013']['translation'])

    def test_hong_kong_edit_invalidates_only_its_own_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for tree in SOURCE_ROOTS:
                (root / tree).mkdir(parents=True)
            path = root / 'corpus/zh-hant-hk/a.json'
            path.parent.mkdir()
            path.write_text('[]')
            self.assertFalse(source_inventory(root, language=''))
            self.assertFalse(source_inventory(root, language='zh-hant-tw'))
            self.assertEqual(source_inventory(root, language='zh-hant-hk')[0]['path'], 'corpus/zh-hant-hk/a.json')


class AssemblyReuseTests(unittest.TestCase):
    def test_changed_image_receipt_inputs_or_force_require_reassembly(self):
        import build_multilang as build
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / 'build/iso/test/experiment/test.iso'
            output.parent.mkdir(parents=True)
            receipt = output.with_suffix('.receipt.json')
            inputs = {'version': '1'}

            def assembled(*_):
                output.write_bytes(b'verified')
                receipt.write_bytes(b'{}')

            with patch.object(build, 'ROOT', root), patch.object(build, 'assembly_inputs', return_value=inputs), \
                    patch.object(build, 'image', return_value=root / 'single.iso'), \
                    patch.object(build, 'run', side_effect=assembled) as run:
                build.assemble('original', output, False)
                build.assemble('original', output, False)
                self.assertEqual(run.call_count, 1)
                output.write_bytes(b'corrupt')
                build.assemble('original', output, False)
                receipt.write_bytes(b'bad')
                build.assemble('original', output, False)
                inputs['version'] = '2'
                build.assemble('original', output, False)
                build.assemble('original', output, True)
                self.assertEqual(run.call_count, 5)
