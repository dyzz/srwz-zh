from pathlib import Path
import json
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from srwz.best_build import BestCompiler, project_shared_edits
from srwz.edition import EditionError
from srwz.stage import _condition_entries
from srwz.text import TextTable


def packed(*values):
    return struct.pack('<'+'I'*len(values),*values)


class BestBackendTests(unittest.TestCase):
    def hsfc_table_compiler(self):
        repo = Path(__file__).resolve().parents[1]
        contract = json.loads((repo / 'config/editions/best/source-layout.json').read_text())
        member = 'DATA/HSFC.BIN'
        spec = next(r for r in contract['archive_tables'] if r['member'] == member)
        compiler = BestCompiler.__new__(BestCompiler)
        compiler.archive_tables = {member: spec}
        compiler.native = {}
        # Real HSFC native layouts: the Best credits block is 0x90 bytes larger.
        for version, name, offsets in [
            ('original', 'SLPS_258.87', [0, 0x2570, 0x39B00, 0x3D030, 0x3D100]),
            ('best', 'SLPS_732.70', [0, 0x2570, 0x39B00, 0x3D0C0, 0x3D190]),
        ]:
            elf = bytearray(b'\xA5' * 0x350000)
            for site in (spec, *spec['aliases']):
                start, count = site[f'{version}_start'], site['count']
                elf[start:start+4*count] = packed(*offsets[:count])
            compiler.native[version] = {name: bytes(elf), member: bytes(offsets[-1])}
        compiler.outputs = {member: bytes(0x3D190)}
        compiler.tables = {member: [0, 0x1D50, 0x36450, 0x39A10, 0x3D190]}
        compiler.elf_writes = []
        return compiler, spec

    def test_hsfc_repacking_updates_both_runtime_consumers_and_preserves_neighbors(self):
        compiler, spec = self.hsfc_table_compiler()
        self.assertEqual(spec['best_start'], 0x347E90)
        self.assertEqual(spec['aliases'][0]['best_start'], 0x33C610)
        self.assertEqual(spec['aliases'][0]['original_start'], 0x33BE20)
        self.assertEqual(spec['aliases'][0]['count'], 5)
        native = compiler.native['best']['SLPS_732.70']
        elf = bytearray(native)
        proof = compiler.write_archive_tables(elf)
        offsets = compiler.tables['DATA/HSFC.BIN']
        # The loader uses [index+1]-[index], including the final end sentinel.
        loader = struct.unpack_from('<5I', elf, 0x33C610)
        self.assertEqual(list(loader), offsets)
        self.assertEqual(list(struct.unpack_from('<4I', elf, 0x347E90)), offsets[:4])
        self.assertEqual([b-a for a, b in zip(loader, loader[1:])],
                         [0x1D50, 0x34700, 0x35C0, 0x3780])
        self.assertEqual(len(proof), 2)
        for start, end in compiler.elf_writes:
            elf[start:end] = native[start:end]
        self.assertEqual(elf, native)  # Includes the adjacent decoded-size table.

    def test_hsfc_stale_or_unknown_native_alias_fails_closed(self):
        for version, name in [('original', 'SLPS_258.87'), ('best', 'SLPS_732.70')]:
            with self.subTest(version=version):
                compiler, spec = self.hsfc_table_compiler()
                elf = bytearray(compiler.native[version][name])
                elf[spec['aliases'][0][f'{version}_start'] + 4] ^= 0x10
                compiler.native[version][name] = bytes(elf)
                with self.assertRaisesRegex(EditionError, 'alias preimage drift'):
                    compiler.write_archive_tables(bytearray(compiler.native['best']['SLPS_732.70']))

    def test_sr_point_alignment_maps_to_best_without_replacing_native_text_pointer(self):
        repo = Path(__file__).resolve().parents[1]
        contract = json.loads((repo / 'config/editions/best/source-layout.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            compiler = BestCompiler.__new__(BestCompiler)
            compiler.root = Path(directory)
            compiler.contract = contract
            compiler.spans = contract['elf_spans']
            compiler.span_starts = [row[0] for row in compiler.spans]
            compiler.archive_tables = {}
            compiler.zh_table = TextTable({0x8FD2: '。'}, {})
            source = bytearray(0x350000)
            native = bytearray(source)
            original_offset, best_offset = 0x253924, 0x253F24
            source[original_offset:original_offset + 8] = bytes.fromhex('ecff0526d8208424')
            native[best_offset:best_offset + 8] = bytes.fromhex('ecff0526c8288424')
            compiled = bytearray(source)
            compiled[original_offset:original_offset + 4] = bytes.fromhex('f4ff0526')
            slot = contract['elf_support_attack_slot']
            compiled[slot['original_start']:slot['original_start'] + 3] = bytes.fromhex('8fd200')
            compiler.native = {'original': {'SLPS_258.87': bytes(source)},
                               'best': {'SLPS_732.70': bytes(native)}}
            compiler.compiled = {'SLPS_258.87': bytes(compiled)}
            corpus = compiler.root / 'corpus/zh/menu/system-ui-skills.json'
            corpus.parent.mkdir(parents=True)
            corpus.write_text(json.dumps({'entries': [{'id': slot['translation_id'], 'translation': '。'}]}))
            result = compiler.compile_elf()
            self.assertEqual(result[best_offset:best_offset + 8], bytes.fromhex('f4ff0526c8288424'))
            native[best_offset] ^= 1
            compiler.native['best']['SLPS_732.70'] = bytes(native)
            with self.assertRaisesRegex(EditionError, 'instruction preimage'):
                compiler.compile_elf()

    def test_shorter_best_slot_preserves_reviewed_punctuation_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            compiler = BestCompiler.__new__(BestCompiler)
            compiler.root = Path(directory)
            slot = {'translation_id':'skill','original_start':0x336470,'original_end':0x3364A8,
                    'best_start':0x336C70,'best_end':0x336CA0}
            source = bytes(0x350000)
            compiled = bytearray(source)
            compiled[slot['original_start']:slot['original_start']+3] = bytes.fromhex('8fd200')
            compiler.native = {'original':{'SLPS_258.87':source},'best':{'SLPS_732.70':source}}
            compiler.compiled = {'SLPS_258.87':bytes(compiled)}
            compiler.contract = {'elf_instructions':[], 'elf_support_attack_slot':slot}
            compiler.archive_tables = {}
            compiler.zh_table = TextTable({0x8142:'。',0x8FD2:'。'}, {})
            corpus = compiler.root/'corpus/zh/menu/system-ui-skills.json'
            corpus.parent.mkdir(parents=True)
            corpus.write_text(json.dumps({'entries':[{'id':'skill','translation':'。'}]}))
            result = compiler.compile_elf()
            self.assertEqual(result[slot['best_start']:slot['best_start']+3],bytes.fromhex('8fd200'))

    def test_native_official_value_already_in_shared_input_is_preserved(self):
        self.assertEqual(project_shared_edits(packed(315),packed(316),packed(316)),packed(316))

    def test_native_only_changes_and_relocated_text_pointers(self):
        self.assertEqual(project_shared_edits(packed(0x756800,7),packed(0x757000,9),packed(0x756840,7)),packed(0x757040,9))

    def test_unknown_overlap_and_neighbor_fields_fail(self):
        with self.assertRaisesRegex(EditionError,'overlap'):
            project_shared_edits(packed(1),packed(2),packed(3))
        with self.assertRaisesRegex(EditionError,'overlap'):
            project_shared_edits(b'abcd',b'AbcD',b'Xbcd',text_mask=b'\1\0\0\0')

    def test_piecewise_inserted_native_bytes_are_preserved(self):
        self.assertEqual(project_shared_edits(b'abcdEFGH',b'1111abcd2222EFGH',b'AbcdEfGH',shift=lambda o:4 if o<4 else 8),b'1111Abcd2222EfGH')

    def test_no_silent_decoded_growth_or_unaligned_tail_write(self):
        for original, native, compiled in [(b'abcd',b'abcd',b'abcde'),(b'abcde',b'abcde',b'abcdE')]:
            with self.subTest(compiled=compiled), self.assertRaises(EditionError):
                project_shared_edits(original,native,compiled)

    def test_best_condition_signatures_parse_without_editing_code(self):
        base = 0x756EF0
        data = bytearray(260)
        for site,table,target,signature in [(16,128,180,'b05a22ac'),(40,136,200,'b85a22ac'),(64,144,220,'c05a22ac')]:
            address = base+table
            struct.pack_into('<H',data,site-12,(address+0x8000)>>16)
            struct.pack_into('<H',data,site-8,address&0xFFFF)
            data[site:site+4] = bytes.fromhex(signature)
            struct.pack_into('<I',data,table,base+target)
            data[target:target+2] = b'A\0'
        frozen = bytes(data)
        entries,_ = _condition_entries(frozen,base,TextTable({},{}),stage_index=1,base_address=base)
        self.assertEqual(len(entries),3)
        self.assertEqual([e.text for e in entries],['A','A','A'])
        self.assertEqual(bytes(data),frozen)
        original_entries,_ = _condition_entries(frozen,base,TextTable({},{}),stage_index=1,base_address=0x7566F0)
        self.assertEqual(original_entries,())


if __name__ == '__main__':
    unittest.main()
