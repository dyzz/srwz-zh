"""Regression tests for current-corpus SP library authoring and field ownership."""
import hashlib
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from special_disc.writeback.shared_library import field_translation, replacement_fields
from special_disc.writeback.migrate_library import serialize
from srwz.text import load_text_table


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


class SharedLibraryTests(unittest.TestCase):
    def setUp(self):
        self.field = SimpleNamespace(tag='ACTR', text='声優', data=b'')
        self.doc = SimpleNamespace(kind='CHAR', fields=[self.field],
            field=lambda tag: SimpleNamespace(text='人物甲'))
        self.rows = {digest('声優'): dict(translation='原声优', domains=['character'], tags=['ACTR'])}
        self.scoped = [dict(id='character/407/ACTR', source_text_sha256=digest('声優'),
            context_text_sha256=digest('人物甲'), translation='专用声优')]

    def test_scoped_credit_uses_character_identity_not_sp_index(self):
        self.assertEqual(field_translation(self.rows, self.scoped, 'character', self.doc, self.field), '专用声优')
        self.doc.field = lambda tag: SimpleNamespace(text='人物乙')
        self.assertEqual(field_translation(self.rows, self.scoped, 'character', self.doc, self.field), '原声优')

    def test_source_hash_requires_compatible_domain_and_tag(self):
        self.assertIsNone(field_translation(self.rows, [], 'robot', self.doc, self.field))
        self.field.tag = 'CHFN'
        self.assertIsNone(field_translation(self.rows, [], 'character', self.doc, self.field))

    def test_ambiguous_scoped_identity_fails(self):
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            field_translation(self.rows, self.scoped*2, 'character', self.doc, self.field)

    def test_unknown_sp_text_and_binary_preserved_but_current_shared_text_replaces_canary(self):
        table = load_text_table(Path(__file__).resolve().parents[1] / 'vendor/upstream-python/project/tbl_all.json')
        native = SimpleNamespace(kind='KYWD', fields=[
            SimpleNamespace(tag='KWFN', text='原名', data=b''),
            SimpleNamespace(tag='ACTR', text='SP専用', data=b''),
            SimpleNamespace(tag='FLAG', text=None, data=b'\x01\x02')])
        rows = {digest('原名'): dict(translation='ABC', domains=['glossary'], tags=['KWFN'])}
        base = serialize('KYWD', 1, [('KWFN', b'old'), ('ACTR', b'untouched'), ('FLAG', b'\x01\x02')])
        fields, counts = replacement_fields(native, base, 'glossary', (rows, [], {}, {}, (), {}), table, {})
        self.assertEqual(fields[1:], [('ACTR', b'untouched'), ('FLAG', b'\x01\x02')])
        self.assertNotEqual(fields[0][1], b'old')
        self.assertEqual(counts['current_shared_fields'], 1)
        native.fields[-1].data = b'\x03\x02'
        with self.assertRaisesRegex(ValueError, 'binary field drift'):
            replacement_fields(native, base, 'glossary', (rows, [], {}, {}, (), {}), table, {})


if __name__ == '__main__':
    unittest.main()
