"""Native scrolling separators must survive corpus, encoding and writeback."""
import struct
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from srwz.summary import parse_summary,validate_scroll_placeholders
from srwz.text import TextTable,encode_text
from srwz.writers import apply_summary_replacements
from srwz.writeback import WritebackError


class ScrollPlaceholderTests(unittest.TestCase):
    def setUp(self):
        self.table=TextTable({0x8140:'　',0x8141:'甲',0x8142:'乙'}, {})
        self.native='甲\n　\n乙'

    def fixture(self):
        data=bytearray(0x6a+64)
        struct.pack_into('<I',data,0x2c,1)
        data[0x3c:0x40]=b'text'
        struct.pack_into('<I',data,0x40,len(data)-0x44)
        struct.pack_into('<I',data,0x66,64)
        payload=encode_text(self.native,self.table,terminate=True)
        data[0x6a:0x6a+len(payload)]=payload
        return bytes(data)

    def test_reflowed_physical_positions_may_change(self):
        validate_scroll_placeholders(self.native,'甲甲\n甲\n　\n乙',label='fixture')

    def test_empty_ascii_missing_added_and_shortened_rows_are_rejected(self):
        for text in ('甲\n\n乙','甲\n \n乙','甲\n乙','甲\n　\n　\n乙'):
            with self.subTest(text=text),self.assertRaises(WritebackError):
                validate_scroll_placeholders(self.native,text,label='fixture')
        with self.assertRaisesRegex(WritebackError,'changed'):
            validate_scroll_placeholders('甲\n'+'　'*21+'\n乙',self.native,label='SP')

    def test_encoded_wrong_glyph_or_empty_row_is_rejected(self):
        for payload in (b'\x81\x41\n\n\x81\x42',b'\x81\x41\n\x81\x43\n\x81\x42'):
            with self.subTest(payload=payload),self.assertRaisesRegex(WritebackError,'0x8140'):
                validate_scroll_placeholders(self.native,self.native,label='ISO',payload=payload)
        validate_scroll_placeholders(self.native,self.native,label='ISO',
                                     payload=encode_text(self.native,self.table,terminate=True)+b'\0'*8)

    def test_shared_writer_rejects_bad_translation_before_patching(self):
        for text in ('甲\n\n乙','甲\n乙'):
            with self.subTest(text=text),self.assertRaises(WritebackError):
                apply_summary_replacements(self.fixture(),self.table,chunk_index=0,
                                           replacements={'summary/00/000':text})

    def test_shared_writer_rejects_space_encoding_override(self):
        with self.assertRaisesRegex(WritebackError,'0x8140'):
            apply_summary_replacements(self.fixture(),self.table,chunk_index=0,
                                       replacements={'summary/00/000':self.native},overrides={'　':0x8143})

    def test_shared_writer_preserves_fixed_allocation_and_readback(self):
        source=self.fixture()
        result=apply_summary_replacements(source,self.table,chunk_index=0,
                                         replacements={'summary/00/000':'乙\n　\n甲'})
        self.assertEqual(result[:0x6a],source[:0x6a])
        self.assertEqual(len(result),len(source))
        self.assertEqual(parse_summary(result,self.table,chunk_index=0).entries[0].text,'乙\n　\n甲')


if __name__=='__main__':unittest.main()
