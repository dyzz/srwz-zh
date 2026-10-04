"""Pool relocation ownership, reference coverage and independent corruption checks."""
import copy
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from srwz import library_work_titles as work
from srwz.text import TextTable, load_text_table, normalize_original_fullwidth_ascii

class WorkTitlePoolTests(unittest.TestCase):
    def setUp(self):
        self.c,self.rows=work.inputs()
        self.c=copy.deepcopy(self.c)
        native=bytearray(self.c['decoded_size'])
        for r in self.c['entries']:
            b=self.rows[r['id']]['source_text'].encode('cp932')+b'\0'
            native[r['offset']:r['offset']+len(b)]=b
            self.assertEqual(work.sha(native[r['offset']:r['offset']+r['capacity']]),r['source_span_sha256'])
            for at in r['pointer_sites']:struct.pack_into('<I',native,at,self.c['base']+r['offset'])
        r=self.c['compact_list_name'];payload=r['source_text'].encode('cp932')+b'\0'
        native[r['offset']:r['offset']+len(payload)]=payload
        for at in r['pointer_sites']:struct.pack_into('<I',native,at,self.c['base']+r['offset'])
        self.native=bytes(native);self.c['decoded_sha256']=work.sha(self.native)
        base=load_text_table(Path(__file__).resolve().parents[1]/'vendor/upstream-python/project/tbl_all.json')
        chars={c for r in [*self.rows.values(),self.c['compact_list_name']] for c in normalize_original_fullwidth_ascii(r['translation']).replace(' ','　')}
        # A deterministic test-only codebook provides every visible canonical glyph.
        self.table=TextTable({0x8800+i:c for i,c in enumerate(sorted(chars))},dict(base.tags))
        self.mock=patch.object(work,'inputs',return_value=(self.c,self.rows));self.mock.start();self.addCleanup(self.mock.stop)

    def build(self,current=None):
        return work.apply_work_title_pool(current or self.native,self.native,self.table,dict(self.table.inverse_characters))

    def test_all_titles_fit_pool_all_55_refs_follow_and_other_bytes_preserved(self):
        output,report=self.build()
        self.assertLessEqual(report['pool_used'],656)
        self.assertEqual(work.verify_work_title_pool(output,self.native,self.table)['pointer_count'],55)
        allowed=set(range(self.c['pool_start'],self.c['pool_end']))
        r=self.c['compact_list_name'];allowed.update(range(r['offset'],r['offset']+r['capacity']))
        for r in self.c['entries']:
            for at in r['pointer_sites']:allowed.update(range(at,at+4))
        self.assertTrue(all(a==b or i in allowed for i,(a,b) in enumerate(zip(self.native,output))))
        self.assertEqual(self.build(output)[0],output)

    def test_unknown_pointer_into_pool_is_rejected(self):
        data=bytearray(self.native);struct.pack_into('<I',data,0,self.c['base']+self.c['pool_start']+2)
        with self.assertRaisesRegex(ValueError,'unowned current reference'):self.build(bytes(data))

    def test_unrecognized_current_pool_is_rejected(self):
        data=bytearray(self.native);data[self.c['pool_start']]=0xAA
        with self.assertRaisesRegex(ValueError,'current pool preimage'):self.build(bytes(data))

    def test_independent_readback_rejects_pointer_text_and_padding_corruption(self):
        output,report=self.build()
        for at in (self.c['entries'][0]['pointer_sites'][0],self.c['pool_start'],self.c['pool_end']-1):
            data=bytearray(output);data[at]^=1
            with self.assertRaises(ValueError):work.verify_work_title_pool(bytes(data),self.native,self.table)

    def test_dome_list_scope_fits_native_slot_and_does_not_change_the_name(self):
        from srwz.text import CONTROL_NOTATION
        output,_=self.build();proof=work.verify_work_title_pool(output,self.native,self.table)['compact_list_name']
        self.assertLessEqual(proof['encoded_size'],32)
        self.assertEqual(CONTROL_NOTATION.sub('',proof['stored_translation']),'D.O.M.E.G-Bit')
        self.assertTrue(proof['stored_translation'].endswith('<space:16>'))
        data=bytearray(output);data[proof['offset']+1]^=1
        with self.assertRaisesRegex(ValueError,'compact list name final mismatch'):
            work.verify_work_title_pool(bytes(data),self.native,self.table)

    def test_canonical_work_title_corpus_remains_plain_for_auto_demo(self):
        self.assertTrue(all('<width:' not in r['translation'] for r in self.rows.values()))
