"""Regression coverage for the complete main-game Q&A display corpus."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from srwz.nisv_strategy_qa import layout_nisv_strategy_qa_records
from srwz.qa_typography import repair_shared, styled_runs, validate_records


class MainQaLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pages = json.loads((ROOT/'corpus/zh/menu/nisv-strategy-qa.json').read_text())['pages']

    def layout(self, page):
        records = page['records']
        source = dict(records=[dict(x=r['position'][0], y=r['position'][1], z=r['position'][2],
                                    style0=r['style'][0], style1=r['style'][1]) for r in records])
        return layout_nisv_strategy_qa_records(source, records,
            glyph_advance_px=19, line_step_y=11, max_last_glyph_x=513)['records']

    def test_all_102_pages_keep_every_character_color_and_z_without_clipping(self):
        self.assertEqual(len(self.pages), 102)
        for page in self.pages:
            with self.subTest(page=page['page']):
                rendered = self.layout(page)
                original = [dict(text=r['translation'], style=r['style'], position=r['position']) for r in page['records']]
                self.assertEqual(styled_runs(rendered), styled_runs(original))
                validate_records(rendered)
                self.assertEqual(repair_shared(copy.deepcopy(rendered)), (rendered, []))

    def test_table_continuations_stay_in_the_description_column(self):
        records = self.layout(self.pages[29])
        guard = next(r for r in records if r['text'] == '防护')
        description = next(r for r in records if r['text'].startswith('气力130'))
        continuation = next(r for r in records if r['text'] == '为80%')
        self.assertGreater(description['position'][0], guard['position'][0])
        self.assertEqual(continuation['position'][0], description['position'][0])

    def test_short_colored_defend_continuation_joins_without_a_stranded_word(self):
        records = self.layout(self.pages[29])
        rows = {}
        for r in records:
            rows.setdefault(r['position'][1], '')
            rows[r['position'][1]] += r['text']
        self.assertTrue(any('中选择防御时必定发动。' in row for row in rows.values()))

    def test_known_numeric_and_word_splits_stay_on_one_display_row(self):
        cases = {12:['0.5%','1.2倍'],24:['2机'],29:['10'],54:['100'],
                 60:['1000','2000'],78:['MAP'],87:['9级'],93:['SR点数'],100:['SR点数']}
        for page, tokens in cases.items():
            rows = {}
            for r in self.layout(self.pages[page-1]):
                rows.setdefault(r['position'][1], '')
                rows[r['position'][1]] += r['text']
            for token in tokens:
                with self.subTest(page=page,token=token):
                    self.assertTrue(any(token in row for row in rows.values()))


if __name__ == '__main__':
    unittest.main()
