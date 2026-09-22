import copy
import json
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/special_disc/writeback')]
from special_disc.writeback.qa_native import (flow, legal_break, native_records,
    repair_shared, styled_runs, shared_records, validate_records, apply_reviewed_qa, metadata)
from special_disc.writeback.qa_layout import page
from srwz.codec import decode_production


def record(text, x, y, color=0):
    return dict(text=text, style=[2,color], position=[x,y,1])


class SpQaNativeTests(unittest.TestCase):
    def test_color_boundary_never_splits_numeric_unit_or_latin(self):
        records,y = flow([dict(text='甲'*22+'10 ',style=[2,0]),
                          dict(text='EN，SR点数和MAP兵器。',style=[2,7])],38,19,25)
        validate_records(records)
        lines = {}
        for r in records:
            lines.setdefault(r['position'][1], '')
            lines[r['position'][1]] += r['text']
        for token in ('10 EN','SR点数','MAP兵器'):
            self.assertTrue(any(token in s for s in lines.values()), token)
        self.assertEqual(styled_runs(records), [((2,0,1),'甲'*22+'10　'),((2,7,1),'EN，SR点数和MAP兵器。')])

    def test_enumeration_separator_and_size_list_are_not_joined(self):
        rs = [record('精神指令　驾驶员养成　',19,25),record('攻击方法',19,36),
              record('体型分为3L·2L·L·M·S',19,58),record('5个等级。',19,69)]
        self.assertEqual(repair_shared(copy.deepcopy(rs)), (rs,[]))

    def test_period_after_fixed_columns_attaches_without_moving_columns(self):
        rs = [record('防护',38,25,14),record('受到的伤害变为80%',190,25,3),record('。',456,36)]
        fixed,proof = repair_shared(copy.deepcopy(rs))
        self.assertEqual(fixed[0:2],rs[0:2])
        self.assertEqual(fixed[-1]['position'],[380,25,1])
        self.assertEqual(styled_runs(fixed),styled_runs(rs))
        self.assertEqual(len(proof),1)

    def test_overflowing_period_keeps_a_readable_tail_and_style(self):
        rs = [record('驾驶小型机体（S～M尺寸）的驾驶员习得，有助于提升伤害',38,25),record('。',38,36)]
        fixed,_ = repair_shared(copy.deepcopy(rs))
        self.assertEqual(fixed[-1]['text'],'提升伤害。')
        validate_records(fixed)
        self.assertEqual(styled_runs(fixed),styled_runs(rs))
        self.assertEqual(repair_shared(copy.deepcopy(fixed)),(fixed,[]))

    def test_runtime_scissor_cell_is_reflowed_without_losing_styled_text(self):
        rs = [record('甲'*20+'具体内容。',76,25,3),record('后续段落。',38,47)]
        fixed,proof = repair_shared(copy.deepcopy(rs))
        validate_records(fixed)
        self.assertEqual(styled_runs(fixed),styled_runs(rs))
        self.assertTrue(any(p.get('kind') == 'runtime_right_edge' for p in proof))
        self.assertTrue(all(r['position'][0]+(len(r['text'])-1)*19 <= 513 for r in fixed))

    def test_all_reviewed_bindings_preserve_exact_user_text(self):
        native = {e['id']:e for e in json.loads((ROOT/'corpus/zh/special-disc/native-text.json').read_text())['entries']}
        bindings = json.loads((ROOT/'config/products/special-disc/qa-layout.json').read_text())['pages']
        self.assertEqual(len(bindings),22)
        for b in bindings:
            e = native[b['id']]
            records = native_records(b,e)
            self.assertEqual(''.join(r['text'] for r in records),e['translation'].replace('\n',''))
            validate_records(records)

    @unittest.skipUnless((ROOT/'work/build/special-disc/baselines/text-canary.xdelta').exists(), 'Local SP baseline unavailable')
    def test_full_component_readback_idempotence_and_protected_archive(self):
        from migrate_slps_text import encoding_tables
        from build_text_candidate import read_member
        from special_disc.source import SOURCE_ISO
        from special_disc.baselines import baseline_iso
        from srwz.iso9660 import scan_iso9660, member_map
        T,_,O,R = encoding_tables(ROOT/'work/build/special-disc/text-candidate/font/proposal.json')
        members = member_map(scan_iso9660(SOURCE_ISO))
        source = read_member(SOURCE_ISO,members,'DATA/NISVDATA.BIN')
        exe = read_member(SOURCE_ISO,members,'SLPS_259.20')
        baseline = baseline_iso('text-canary')
        fixture = read_member(baseline,member_map(scan_iso9660(baseline)),'DATA/NISVDATA.BIN')
        output,report = apply_reviewed_qa(fixture,exe,source,T,O,runtime_table=R)
        rerun,second = apply_reviewed_qa(output,exe,source,T,O,runtime_table=R)
        self.assertEqual(rerun,output)
        self.assertEqual(second['changed_pages'],[])
        with self.assertRaisesRegex(ValueError, 'Concurrent shared Q&A text/style drift'):
            apply_reviewed_qa(source,exe,source,T,O,runtime_table=R)
        a,b = struct.unpack_from('<II',exe,0x384A00+24)
        chunk = decode_production(output[a:b]).output
        jp = decode_production(source[a:b]).output
        before = decode_production(fixture[a:b]).output
        self.assertEqual(chunk[:0x476],jp[:0x476])
        self.assertEqual(len(metadata(chunk)),264)
        for n in range(1,103):
            if n not in report['native_pages']:
                self.assertEqual(styled_runs(shared_records(page(before,n),R)),
                                 styled_runs(shared_records(page(chunk,n),R)))
            self.assertEqual(page(chunk,n)['sprite_bytes'],page(jp,n)['sprite_bytes'])
            self.assertEqual(page(chunk,n)['size'],page(jp,n)['size'])


if __name__ == '__main__':
    unittest.main()
