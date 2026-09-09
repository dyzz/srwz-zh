import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from srwz.nisv_strategy_qa import layout_nisv_strategy_qa_page


def layout(records, limit=532):
    source = {'records': [dict(zip(('x', 'y', 'z'), r['position'])) for r in records]}
    return layout_nisv_strategy_qa_page(
        source, records, glyph_advance_px=19, line_step_y=11,
        max_last_glyph_x=limit,
    )['positions']


class QaPunctuationTests(unittest.TestCase):
    def test_sr_warning_moves_with_period_and_keeps_full_quote_inside_view(self):
        corpus = json.loads((ROOT / 'corpus/zh/menu/nisv-strategy-qa.json').read_text())
        records = corpus['pages'][92]['records']
        before = json.dumps(records, ensure_ascii=False)
        positions = layout(records)
        self.assertEqual(records[13]['translation'], '“SR点数获得不可”')
        self.assertEqual(records[13]['style'], [2, 7])
        self.assertEqual(records[14]['style'], [2, 0])
        self.assertEqual(positions[13], (19, 91, 1))
        self.assertEqual(positions[14], (209, 91, 1))
        self.assertEqual(json.dumps(records, ensure_ascii=False), before)

    def test_empty_records_do_not_break_punctuation_attachment(self):
        records = [
            {'source': 'aaaa', 'translation': '甲乙丙', 'position': [0, 25, 1]},
            {'source': 'b', 'translation': '', 'position': [0, 36, 1]},
            {'source': 'c', 'translation': '丁', 'position': [19, 36, 1]},
            {'source': 'd', 'translation': '。', 'position': [38, 36, 1]},
        ]
        positions = layout(records, limit=57)
        self.assertEqual(positions[2], (0, 36, 1))
        self.assertEqual(positions[3], (19, 36, 1))

    def test_punctuation_does_not_attach_across_a_paragraph_gap(self):
        records = [
            {'source': 'aaaa', 'translation': '甲乙丙丁', 'position': [0, 25, 1]},
            {'source': 'b', 'translation': '。', 'position': [0, 47, 1]},
        ]
        self.assertEqual(layout(records, limit=57), ((0, 25, 1), (0, 47, 1)))

    def test_fixed_column_anchors_remain_independent(self):
        records = [
            {'source': 'a', 'translation': '甲', 'position': [0, 25, 1]},
            {'source': 'b', 'translation': '。', 'position': [57, 25, 1]},
            {'source': 'c', 'translation': '乙', 'position': [0, 36, 1]},
            {'source': 'd', 'translation': '。', 'position': [57, 36, 1]},
        ]
        self.assertEqual(layout(records, limit=57),
                         ((0, 25, 1), (57, 25, 1), (0, 36, 1), (57, 36, 1)))


if __name__ == '__main__':
    unittest.main()
