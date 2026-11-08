import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('corpus_integration', ROOT / 'tools/text_layout/integrate_tag_free_corpus.py')
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


class CorpusIntegrationTests(unittest.TestCase):
    def fixture(self, root):
        def write(relative, value):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(migration.encoded(value))
            return path
        source = write('corpus/zh/story-dialogue/stage-001.json', {'entries':[{'translation':'目标<z>Side 3</z>。'}]})
        write('corpus/zh/menu/test.json', {'entries':[{'translation':'CIWS/<z>RX-78</z>'}]})
        write('config/test.json', {'corpus':{'path':source.relative_to(root).as_posix(),'sha256':migration.digest(source.read_bytes()),'size':source.stat().st_size}})
        projected = write('projection/story.json', {'entries':[{'translation':'目标Side 3。'}]})
        write('projection/receipt.json', {'complete':True,'rejected':0,'keywordOwnershipVerified':True,'inputs':{},'files':[
            {'source':source.relative_to(root).as_posix(),'sourceSha256':migration.digest(source.read_bytes()),
             'candidate':'story.json','candidateSha256':migration.digest(projected.read_bytes())}]})
        return source

    def test_complete_migration_updates_locks_and_keeps_preimages(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.fixture(root)
            original = source.read_bytes()
            migration.integrate(root,root/'projection',root/'audit')
            self.assertEqual((root/'audit/before'/source.relative_to(root)).read_bytes(), original)
            self.assertNotIn('<z>',source.read_text())
            self.assertEqual(json.loads((root/'config/test.json').read_text())['corpus']['sha256'], migration.digest(source.read_bytes()))
            self.assertNotIn('<z>',(root/'corpus/zh/menu/test.json').read_text())
            self.assertEqual(json.loads((root/'config/text-layout/rendering-mode.json').read_text())['mode'],'proportional')
            self.assertFalse((root/'build').exists())

    def test_stale_source_aborts_before_any_other_write(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.fixture(root)
            source.write_text('{}')
            with self.assertRaisesRegex(ValueError,'source changed'):
                migration.integrate(root,root/'projection',root/'audit')
            self.assertFalse((root/'audit').exists())
            self.assertIn('<z>',(root/'corpus/zh/menu/test.json').read_text())

    def test_incomplete_projection_cannot_enable_policy(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            self.fixture(root)
            receipt=root/'projection/receipt.json'
            value=json.loads(receipt.read_text());value['complete']=False
            receipt.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError,'incomplete'):
                migration.integrate(root,root/'projection',root/'audit')
            self.assertFalse((root/'config/text-layout').exists())
