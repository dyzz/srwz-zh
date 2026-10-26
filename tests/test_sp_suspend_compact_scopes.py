import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from special_disc.writeback import migrate_slps_text as migration
from srwz.text import encode_text, load_text_table


class SuspendCompactScopeTests(unittest.TestCase):
    def test_compact_scope_bytes_and_fixed_slot_boundary(self):
        table = load_text_table(ROOT / 'vendor/upstream-python/project/tbl_all.json')
        overrides = {'P': 0x826F, 'S': 0x8272, '2': 0x8251}
        speaker = encode_text('亜', table) + b'\n'
        source = speaker + encode_text('亜', table, terminate=True)
        translation = '亜<z>PS2</z>亜'
        expected = (speaker + encode_text('亜', table)
                    + bytes.fromhex('32 0e 34 0c 33 0b 82 6f 82 72 82 51 32 15 34 15 33 0c')
                    + encode_text('亜', table, terminate=True))
        corpus = {'entries': [{
            'id': 'story/000/system-dialogue/test',
            'source_text_sha256': migration.sha256_text('亜'),
            'speaker': '亜', 'translation': translation,
            'editorial_status': 'reviewed',
        }]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'zh').mkdir()
            (root / 'zh/story-system-dialogue.json').write_text(
                json.dumps(corpus, ensure_ascii=False), encoding='utf-8')
            for capacity in (len(expected), len(expected) - 1):
                with self.subTest(capacity=capacity):
                    before = b'PREFIX' + source.ljust(capacity, b'\0') + b'SUFFIX'
                    exe = bytearray(before)
                    with patch.object(migration, 'CORPUS', root), patch.object(
                            migration, 'SUSPEND_REGION', (6, 6 + capacity)):
                        report = migration.suspend_messages(exe, table, overrides)
                    self.assertEqual(report['found'], 1)
                    self.assertEqual(report['missing'], [])
                    if capacity == len(expected):
                        self.assertEqual(bytes(exe), b'PREFIX' + expected + b'SUFFIX')
                        self.assertEqual(len(report['rewritten']), 1)
                        self.assertEqual(report['rewritten'][0]['chinese'], translation)
                        self.assertEqual(report['overflow'], [])
                    else:
                        self.assertEqual(bytes(exe), before)
                        self.assertEqual(report['rewritten'], [])
                        self.assertEqual(report['overflow'][0]['needs'], len(expected))
                        self.assertEqual(report['overflow'][0]['capacity'], capacity)


if __name__ == '__main__':
    unittest.main()
