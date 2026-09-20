from __future__ import annotations

import collections
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'tools/special_disc/writeback')]
from srwz.stage import parse_stage
from srwz.text import TextTable
from srwz.writers import repack_stage_texts_in_place
from srwz.writeback import WritebackError
from stage_bindings import StageBindings, BindingError, digest
from migrate_stage_dialogue import reject_interior_references, check_unowned_bytes, native_id


class SpecialDiscStageTests(unittest.TestCase):
    def fixture(self, base=0x8045F0, control=0x63):
        data = bytearray(0x400)
        for index, target in enumerate((0x100, 0x120, 0x140)):
            address = base + target
            struct.pack_into('<H', data, 0x90 + index*16, ((address + 0x8000) >> 16) & 0xFFFF)
            struct.pack_into('<H', data, 0x98 + index*16, address & 0xFFFF)
        struct.pack_into('<II', data, 0x120, base + 0x160, 1)
        struct.pack_into('<II', data, 0x140, 0, 1)
        struct.pack_into('<II', data, 0x160, base + 0x180, 0)
        struct.pack_into('<I', data, 0x1A0, control)
        struct.pack_into('<I', data, 0x1B0, base + 0x200)
        struct.pack_into('<I', data, 0x1C0, 0x7E)
        data[0x200:0x209] = b'Pilot\nHi\0'
        data[0x211:0x21B] = b'UNKNOWN!!!'
        return bytes(data)

    def test_sp_control_is_not_enabled_for_original_or_best(self):
        for base in (0x7566F0, 0x756EF0, 0x8045F0):
            with self.subTest(base=base):
                parsed = parse_stage(self.fixture(base), TextTable({}, {}), stage_index=1, base_address=base)
                self.assertEqual(parsed.dialogue_count, int(base == 0x8045F0))
                normal = parse_stage(self.fixture(base, 0x60), TextTable({}, {}), stage_index=1, base_address=base)
                self.assertEqual(normal.dialogue_count, 1)

    def test_condition_signatures_for_all_three_editions(self):
        for base, signature in ((0x7566F0,'b05222ac'),(0x756EF0,'b05a22ac'),(0x8045F0,'b0e122ac')):
            with self.subTest(base=base):
                data = bytearray(self.fixture(base, 0x60))
                pointer = base + 0x380
                struct.pack_into('<I',data,0x300,0x3C020000 | ((pointer+0x8000)>>16))
                struct.pack_into('<I',data,0x304,0x24420000 | (pointer & 0xFFFF))
                data[0x30C:0x310] = bytes.fromhex(signature)
                struct.pack_into('<I',data,0x380,base+0x390)
                data[0x390:0x394] = b'Win\0'
                parsed = parse_stage(bytes(data),TextTable({},{}),stage_index=1,base_address=base,function_address=base+0x300)
                self.assertEqual([e.text for e in parsed.entries if e.kind=='condition'],['Win'])

    def test_noop_is_byte_exact_and_translation_keeps_prefix_and_unknown_tail(self):
        data=self.fixture(); table=TextTable({}, {})
        for text in ('Hi','Hello'):
            result=repack_stage_texts_in_place(data,table,stage_index=1,function_address=0,base_address=0x8045F0,
                replacements={'story/001/dialogue/01.01/0000':text})
            self.assertEqual(result.data[0x211:], data[0x211:])
            self.assertTrue(result.data[0x200:].startswith(b'Pilot\n'+text.encode()+b'\0'))
            check_unowned_bytes(data,result.data,result.owned_regions,[a.pointer_offset for a in result.allocations])
            if text=='Hi': self.assertEqual(result.data,data)

    def test_unknown_interior_reference_blocks_relocation(self):
        data=bytearray(self.fixture());struct.pack_into('<I',data,0x50,0x8045F0+0x202)
        parsed=parse_stage(bytes(data),TextTable({},{}),stage_index=1,base_address=0x8045F0)
        with self.assertRaisesRegex(WritebackError,'interior reference'):
            reject_interior_references(bytes(data),parsed)

    def test_unowned_byte_audit_detects_event_change(self):
        before=self.fixture();after=bytearray(before);after[0x54]^=1
        with self.assertRaisesRegex(WritebackError,'unowned byte'):
            check_unowned_bytes(before,bytes(after),[(0x200,0x210)],[0x1B0])

    def test_native_challenge_ids_keep_chunk_number(self):
        self.assertEqual(native_id(39,'story/039/dialogue/01.01/0001'),'sd/challenge/039/dialogue/01.01/0001')


    def test_typed_scalar_exclusion_does_not_ignore_other_references(self):
        data=bytearray(self.fixture());struct.pack_into('<I',data,0x50,0x8045F0+0x202)
        parsed=parse_stage(bytes(data),TextTable({},{}),stage_index=1,base_address=0x8045F0)
        reject_interior_references(bytes(data),parsed,nonpointer_sites=[0x50])
        struct.pack_into('<I',data,0x54,0x8045F0+0x203)
        with self.assertRaisesRegex(WritebackError,'0x54'):
            reject_interior_references(bytes(data),parsed,nonpointer_sites=[0x50])

    def test_scalar_contract_locks_record_and_consumer(self):
        import tempfile,json,hashlib
        from stage_auxiliary import scalar_sites
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'config/products/special-disc/stage-scalar-contracts.json'
            path.parent.mkdir(parents=True)
            exe=b'consumer';data=struct.pack('<4I',0x13AB,0x80F000,0x80,0)
            path.write_text(json.dumps(dict(exe_sha256=hashlib.sha256(exe).hexdigest(),consumer_spans=[dict(offset=0,hex=exe.hex())],records=[dict(chunk=21,record_offset=0,record_hex=data.hex())])))
            self.assertEqual(scalar_sites(data,21,root,exe),[4])
            with self.assertRaisesRegex(ValueError,'record preimage'):
                scalar_sites(data[:-1]+b'1',21,root,exe)
            with self.assertRaisesRegex(ValueError,'executable drift'):
                scalar_sites(data,21,root,b'other')

    def test_full_title_delta_rejects_conflicting_component(self):
        from build_full_text import merge_delta
        self.assertEqual(merge_delta(b'AXC',b'ABC',b'ABD'),(b'AXD',1))
        with self.assertRaisesRegex(ValueError,'preimage'):
            merge_delta(b'ABX',b'ABC',b'ABD')

    def test_fixed_paragraph_indent_fits_total_width(self):
        from write_frame_text import paragraphs
        from srwz.chinese_layout import rendered_line_width
        lines=paragraphs('　这是一个用于验证固定页首行缩进和换行宽度的文本。',12)
        self.assertTrue(lines[0].startswith('　'))
        self.assertGreater(len(lines),1)
        for line in lines:
            self.assertLessEqual(len(line)-len(line.lstrip('　'))+rendered_line_width(line),12)
        self.assertEqual(''.join(lines).replace('　',''),'这是一个用于验证固定页首行缩进和换行宽度的文本。')


class SpecialDiscBindingTests(unittest.TestCase):
    def binder(self):
        result=StageBindings.__new__(StageBindings)
        result.allow_draft=True;result.direct={};result.fallback=collections.defaultdict(list)
        result.sp_fallback=collections.defaultdict(list)
        return result

    def row(self,translation,status='draft'):
        return dict(id=translation,source_text_sha256=digest('はい'),translation=translation,
                    editorial_status=status,corpus='fixture')

    def test_identical_source_keeps_context_specific_native_answers(self):
        binder=self.binder();binder.direct={'one':self.row('好'),'two':self.row('是')}
        self.assertEqual(binder.resolve('one','dialogue','はい')['translation'],'好')
        self.assertEqual(binder.resolve('two','dialogue','はい')['translation'],'是')

    def test_native_preimage_drift_cannot_fall_back(self):
        binder=self.binder();binder.direct={'one':self.row('好')}
        with self.assertRaisesRegex(BindingError,'native source drift'):
            binder.resolve('one','dialogue','違う')

    def test_ambiguous_hash_is_rejected_independently_of_order(self):
        binder=self.binder()
        for rows in ([self.row('好'),self.row('是')],[self.row('是'),self.row('好')]):
            binder.fallback['dialogue',digest('はい')]=rows
            with self.assertRaisesRegex(BindingError,'2 fallback answers'):
                binder.resolve('one','dialogue','はい')

    def test_draft_gate_and_unique_reviewed_fallback(self):
        binder=self.binder();binder.allow_draft=False;binder.direct={'one':self.row('好')}
        with self.assertRaisesRegex(BindingError,'allow-draft'):
            binder.resolve('one','dialogue','はい')
        binder.fallback['dialogue',digest('はい')]=[self.row('好','reviewed'),self.row('好','reviewed')]
        self.assertEqual(binder.resolve('two','dialogue','はい')['translation'],'好')


if __name__=='__main__': unittest.main()
