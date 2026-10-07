"""Catch invisible control-code changes and stale copies outside the roster table."""
import json
import hashlib
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/special_disc/writeback')]
from special_disc.writeback.battle_viewer_descriptions import verify_name_marker
from special_disc.writeback.write_system_text import Writer
from special_disc.writeback import shared_label_updates as labels
from special_disc.writeback.migrate_slps_text import encoding_tables
from srwz.text import decode_text, encode_text


class ViewerTextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        registry = json.loads((ROOT / 'config/encoding/zh-release-font-assignments.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'proposal.json'
            path.write_text(json.dumps(dict(assignments=registry['primary_assignments'],
                surface_alias_assignments=registry['surface_alias_assignments'],
                source_compatibility_assignments=registry['source_compatibility_assignments'])))
            cls.table, _, cls.overrides, cls.readback = encoding_tables(path)

    def test_name_marker_is_native_only_in_viewer_descriptions(self):
        writer = Writer(self.table, self.overrides, self.readback)
        source, text, target = '味方として登場した※です。', '作为友军登场的※。', 'sd/compdata/98730'
        raw = writer.encode(text, target, source)
        self.assertIn(b'\x81\xa6', raw)
        self.assertNotIn(b'\x96\x56', raw)
        self.assertEqual(verify_name_marker(raw, target, source, text), 1)
        # Both byte forms decode to ※; semantic readback alone misses the bug.
        broken = raw.replace(b'\x81\xa6', b'\x96\x56')
        self.assertEqual(decode_text(raw, 0, self.readback).text,
                         decode_text(broken, 0, self.readback).text)
        with self.assertRaisesRegex(ValueError, 'native name substitution'):
            verify_name_marker(broken, target, source, text)
        self.assertEqual(writer.encode('※注意', 'sd/compdata/90000', '※注意')[:2], b'\x96\x56')
        with self.assertRaisesRegex(ValueError, 'count changed'):
            writer.encode('作为友军登场。', target, source)

    def test_every_viewer_marker_has_source_and_translation_coverage(self):
        writer = Writer(self.table, self.overrides, self.readback)
        corpus = json.loads((ROOT / 'corpus/zh/special-disc/system-text.json').read_text())
        rows = [r for r in corpus['entries'] if r['category'] == '战斗鉴赏：机体／驾驶员列表'
                and '※' in r['source_text']]
        self.assertEqual(len(rows), 44)
        self.assertEqual(sum(verify_name_marker(writer.encode(r['translation'], r['id'], r['source_text']),
                             r['id'], r['source_text'], r['translation']) for r in rows), 44)

    def fixture(self):
        contract, rows, _ = labels.inputs()
        data = bytearray(contract['decoded_size'])
        for slot, _ in rows:
            at, size = slot['offset'], slot['capacity']
            data[at:at + size] = bytes.fromhex(slot['previous_hex'])
            for site in slot['reference_sites']:
                struct.pack_into('<I', data, site, contract['runtime_base'] + at)
        return bytes(data), rows

    def test_updates_owned_duplicates_from_current_corpora(self):
        before, rows = self.fixture()
        output, report = labels.patch_decoded(before, self.table, self.overrides, self.readback)
        restored = bytearray(output)
        for slot, text in rows:
            at, size = slot['offset'], slot['capacity']
            self.assertEqual(decode_text(output, at, self.readback).text, text)
            self.assertNotIn('飞天神机', text)
            restored[at:at + size] = before[at:at + size]
        self.assertEqual(restored, before)
        self.assertEqual(len(report['labels']), 63)
        self.assertEqual(labels.patch_decoded(output, self.table, self.overrides, self.readback)[0], output)

    def test_viewer_pilot_aliases_are_bound_to_existing_reviewed_names(self):
        contract, rows, _ = labels.inputs()
        reference = json.loads((ROOT / 'config/products/special-disc/shared-name-reference.json').read_text())['pilots']
        pilots = [(s, t) for s, t in rows if 0x9B000 <= s['offset'] <= 0x9EE80]
        self.assertEqual(len(pilots), 58)
        for slot, text in pilots:
            self.assertEqual(reference[slot['source_text']], [text])
        self.assertNotIn('ダヴ', {s['source_text'] for s, _ in pilots})
        self.assertEqual(contract['viewer_pilot_list']['inherited_redirects'][0]['current_text'], 'Dove')

    def test_separate_viewer_table_rejects_japanese_and_redirected_names(self):
        contract, _, _ = labels.inputs()
        data = bytearray(contract['decoded_size'])
        at = 0x90000
        raw = encode_text('丹泽尔', self.table, overrides=self.overrides, terminate=True)
        data[at:at + len(raw)] = raw
        metadata = bytearray()
        for index in range(554):
            record = 0x71200 + 48 * index
            struct.pack_into('<II', data, record, index, 0x764F80 + at)
            metadata.extend(data[record:record + 8])
        contract['viewer_pilot_list']['identity_and_name_pointers_sha256'] = hashlib.sha256(metadata).hexdigest()
        with patch.object(labels, 'inputs', return_value=(contract, [], {})):
            self.assertEqual(labels.audit_viewer_pilot_labels(bytes(data), self.readback)['records'], 554)
            broken = bytearray(data)
            broken[at:at + 16] = bytes.fromhex('83668393835b838b00') + bytes(7)
            with self.assertRaisesRegex(ValueError, 'untranslated name'):
                labels.audit_viewer_pilot_labels(bytes(broken), self.readback)
            broken = bytearray(data)
            struct.pack_into('<I', broken, 0x71204, 0x764F80 + at + 2)
            with self.assertRaisesRegex(ValueError, 'identity or pointer drift'):
                labels.audit_viewer_pilot_labels(bytes(broken), self.readback)

    def test_rejects_unowned_reference_and_unknown_preimage(self):
        data, rows = self.fixture()
        broken = bytearray(data)
        struct.pack_into('<I', broken, 0x100, 0x764F80 + rows[0][0]['offset'] + 2)
        with self.assertRaisesRegex(ValueError, 'interior reference'):
            labels.patch_decoded(bytes(broken), self.table, self.overrides, self.readback)
        broken = bytearray(data)
        broken[rows[0][0]['offset']] ^= 1
        with self.assertRaisesRegex(ValueError, 'preimage drift'):
            labels.patch_decoded(bytes(broken), self.table, self.overrides, self.readback)


if __name__ == '__main__':
    unittest.main()
