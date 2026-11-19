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
    def test_missing_file_row_and_field(self):
        class Dictionary(fill_corpora.sc.Drafter):
            def __init__(self, path):
                self.frozen = set()

            def text(self, value):
                return value.replace('机', '機').replace('发', '發')

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / 'corpus/zh/stage.json'
            tw = root / 'corpus/zh-hant/stage.json'
            hk = root / 'corpus/zh-hant-hk/stage.json'
            src.parent.mkdir(parents=True)
            tw.parent.mkdir(parents=True)
            src.write_text(json.dumps({'language': 'zh-Hans', 'entries': [
                {'id': 'a', 'translation': '出发', 'source': '原机'},
                {'id': 'b', 'translation': '机体'},
                {'id': 'c', 'translation': '出发'}]}))
            tw.write_text(json.dumps({'entries': [{'id': 'c', 'translation': ''},
                                                   {'id': 'a', 'translation': '編輯定稿'}]}))
            with patch.object(fill_corpora.sc, 'Drafter', Dictionary):
                fill_corpora.prepare(root)
                first = hk.stat().st_mtime_ns
                fill_corpora.prepare(root)
            a, b, c = json.loads(tw.read_text())['entries']
            self.assertEqual((a['translation'], a['source']), ('編輯定稿', '原机'))
            self.assertEqual((b['translation'], c['translation']), ('機体', '出發'))
            self.assertEqual(json.loads(hk.read_text())['entries'][0]['translation'], '出發')
            self.assertEqual(first, hk.stat().st_mtime_ns)

    def test_missing_terrain_name_matches_the_japanese_source(self):
        source = [{'source': '甲', 'translation': '第一'}, {'source': '乙', 'translation': '第二'}]
        existing = [{'source': '乙', 'translation': '人工譯文'}]
        self.assertEqual(fill_corpora.fill(source, existing), [source[0], existing[0]])

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
            output = root / 'test.iso'
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
