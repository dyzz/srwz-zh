import json
from pathlib import Path
import re
import sys
import struct
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from srwz.nisv_strategy_qa import layout_nisv_strategy_qa_page
from srwz.codec import decode_production, reencode_changed_suffix
from srwz.text import PreparedTextEncoder
from srwz.qa_typography import shared_records, styled_runs, pack_page
from special_disc.writeback.qa_layout import apply_qa_layout, page


class QaNumericLayoutTests(unittest.TestCase):
    def test_page_12_numeric_units_are_complete_on_display_rows(self):
        records = json.loads((ROOT / 'corpus/zh/menu/nisv-strategy-qa.json').read_text())['pages'][11]['records']
        source = {'records': [dict(zip(('x', 'y', 'z'), r['position'])) for r in records]}
        positions = layout_nisv_strategy_qa_page(source, records, glyph_advance_px=19,
            line_step_y=11, max_last_glyph_x=532)['positions']
        rows = {}
        for r, (x, y, _) in zip(records, positions):
            text = r['translation']
            if text:
                self.assertLessEqual(x + (len(text)-1)*19, 532)
                rows.setdefault(y, []).append((x, text))
        lines = [''.join(text for _, text in sorted(parts)) for parts in rows.values()]
        for token in ('0.5%', '1.2倍', '3机', '格斗武器', '伤害比例'):
            self.assertTrue(any(token in line for line in lines), token)
        self.assertFalse(any(re.match(r'^\.[0-9]', line) for line in lines))

    def test_page_12_keeps_all_original_translation_characters_and_styles(self):
        records = json.loads((ROOT / 'corpus/zh/menu/nisv-strategy-qa.json').read_text())['pages'][11]['records']
        self.assertEqual(''.join(r['translation'] for r in records[3:8]),
            '可提升驾驶员的格斗或射击，分别增加格斗武器或射击武器的伤害。能力值每上升1点，伤害基本增加0.5%。该数值可能因其他因素增减。')
        self.assertEqual(''.join(r['translation'] for r in records[18:20]),
            '参加小队攻击时，伤害变为通常小队攻击的1.2倍。')
        for index in (3, 4, 5, 18, 19, 21, 22, 24, 25):
            self.assertEqual(records[index]['style'], [2, 0])

    @unittest.skipUnless((ROOT / 'work/build/special-disc/components/nisv/DATA/NISVDATA.BIN').exists(),
                         'SP local component fixture unavailable')
    def test_sp_page_refresh_preserves_other_pages_and_is_idempotent(self):
        sys.path.insert(0, str(ROOT / 'tools/special_disc/writeback'))
        from migrate_slps_text import encoding_tables
        from build_text_candidate import read_member
        from srwz.iso9660 import member_map, scan_iso9660
        from special_disc.source import SOURCE_ISO
        members = member_map(scan_iso9660(SOURCE_ISO))
        exe = read_member(SOURCE_ISO, members, 'SLPS_259.20')
        source = read_member(SOURCE_ISO, members, 'DATA/NISVDATA.BIN')
        archive = (ROOT / 'work/build/special-disc/components/nisv/DATA/NISVDATA.BIN').read_bytes()
        table, _, overrides, runtime = encoding_tables(ROOT / 'work/build/special-disc/text-candidate/font/proposal.json')
        a, b = struct.unpack_from('<II', exe, 0x384A00 + 24)
        # This legacy helper only changes layout within an already encoded page.
        # Bind the old local fixture to current codes before testing that contract;
        # qa_native tests separately cover primary-to-alias migration.
        decoded = decode_production(archive[a:b])
        current = bytearray(decoded.output)
        target = page(current, 12)
        records = shared_records(target, runtime)
        payload, _ = pack_page(target, records, PreparedTextEncoder(table, overrides), runtime)
        start, size = target['start'], target['size']
        current[start:start + size] = payload
        self.assertEqual(styled_runs(shared_records(page(current, 12), runtime)), styled_runs(records))
        packed = reencode_changed_suffix(archive[a:b], bytes(current), strategy='rust-maximum',
                                        max_output_size=b-a, original_result=decoded)
        self.assertEqual(decode_production(packed).output, bytes(current))
        archive = archive[:a] + packed + bytes(b-a-len(packed)) + archive[b:]
        output, report = apply_qa_layout(archive, exe, source, table, overrides)
        before, after = [decode_production(data[a:b]).output for data in (archive, output)]
        target = page(before, 12)
        restored = bytearray(after)
        start, size = target['start'], target['size']
        restored[start:start+size] = before[start:start+size]
        self.assertEqual(restored, before)
        self.assertEqual(output[:a], archive[:a])
        self.assertEqual(output[b:], archive[b:])
        self.assertEqual(report['pages'], [12])
        self.assertEqual(apply_qa_layout(output, exe, source, table, overrides)[0], output)
        with self.assertRaisesRegex(ValueError, 'translated text/style drift'):
            apply_qa_layout(source, exe, source, table, overrides)


if __name__ == '__main__':
    unittest.main()
