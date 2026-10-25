import json
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from srwz.compact_scopes import STORY, collapse, expand
from srwz.chinese_layout import dialogue_line_widths, fit_chinese_dialogue_layout, load_layout_profiles
from srwz.compact_authoring import compact_controlled_text, unscoped_text
from srwz.text import SrwzTextEncodeError, TextTable, encode_text, unrecognized_control_notation_offsets

STORY_FILES = [*sorted((ROOT / 'corpus/zh/story-dialogue').glob('stage-*.json')),
               ROOT / 'corpus/zh/story-system-dialogue.json',
               ROOT / 'corpus/zh/special-disc/story-dialogue.json',
               ROOT / 'corpus/zh/special-disc/challenge-dialogue.json']


class CompactScopeTests(unittest.TestCase):
    def test_every_scope_sets_and_restores_all_three_dimensions(self):
        self.assertEqual(expand('攻击<z>PLANT</z>的'),
                         '攻击<width:0E><space:0C><height:0B>PLANT<width:15><space:15><height:0C>的')
        self.assertEqual(expand('<z>100</z>万'),
                         '<width:0E><space:0C><height:0B>100<width:15><space:15><height:0C>万')
        # Story letters and digits share height 11, so a mixed run needs no switch.
        self.assertEqual(expand('<z>RX-78F14</z>'),
                         '<width:0E><space:0C><height:0B>RX-78F14<width:15><space:15><height:0C>')

    def test_class_heights_switch_inside_a_run(self):
        # Height 10 must not be the raw line-feed parameter 0A.
        metrics = {**STORY, 'digit': 0x8A}
        self.assertEqual(expand('<z>RX-78F14</z>', metrics),
                         '<width:0E><space:0C><height:0B>RX-<height:8A>78<height:0B>F<height:8A>14'
                         '<width:15><space:15><height:0C>')

    def test_keyword_body_keeps_one_height(self):
        self.assertEqual(expand('<z>《Side 3》</z>'),
                         '<width:0E><space:0C><height:0B>《Side 3》<width:15><space:15><height:0C>')
        metrics = {**STORY, 'digit': 0x8A}
        self.assertEqual(expand('<z>《3D》</z>', metrics),
                         '<width:0E><space:0C><height:8A>《3D》<width:15><space:15><height:0C>')
        self.assertEqual(expand('<z>《Side 3》</z>', metrics),
                         '<width:0E><space:0C><height:0B>《Side 3》<width:15><space:15><height:0C>')

    def test_percent_restores_advance_first(self):
        self.assertEqual(expand('<z>99.9%</z>'),
                         '<width:0E><space:0C><height:0B>99.9%<space:15><width:15><height:0C>')

    def test_collapse_inverts_expand_only(self):
        for text in ('“<z>D.O.M.E</z>.……”', '<z>THE HEAT</z>与<z>100</z>', '<z>King～King</z>'):
            self.assertEqual(collapse(expand(text)), text)
        foreign = '<width:0E><space:0C><height:0C>PLANT<width:15><space:15><height:0C>'
        self.assertEqual(collapse(foreign), foreign)

    def test_malformed_scopes_are_rejected(self):
        for text in ('<z>中文</z>', '<z>A', 'A</z>', '<z><z>A</z></z>', '<z></z>', '<z>(1+2)</z>', '<z>[4]</z>'):
            with self.assertRaises(ValueError, msg=text):
                expand(text)

    def test_unexpanded_scope_never_reaches_the_encoder(self):
        table = TextTable(characters={0x889F: '亜'}, tags={})
        self.assertEqual(unrecognized_control_notation_offsets('亜<z>A</z>'), ())
        with self.assertRaises(SrwzTextEncodeError):
            encode_text('亜<z>A</z>', table)
        with self.assertRaises(SrwzTextEncodeError):
            encode_text('亜</z>', table)

    def test_layout_measures_native_and_returns_author_form(self):
        profile = load_layout_profiles(ROOT / 'config/text-layout/zh-layout-profiles.json')['story_dialogue']
        authored = '“攻击目标是<z>PLANT</z>吗！！”'
        self.assertEqual(dialogue_line_widths(authored, default_advance_px=21),
                         dialogue_line_widths(expand(authored), default_advance_px=21))
        self.assertEqual(fit_chinese_dialogue_layout(authored, profile=profile).text, authored)
        self.assertEqual(unscoped_text(authored), '“攻击目标是PLANT吗！！”')

    def test_story_authoring_writes_z(self):
        result = compact_controlled_text('攻击PLANT与99%', default_width=21, notation='z')
        self.assertEqual(result, '攻击<z>PLANT</z>与<z>99%</z>')
        self.assertEqual(compact_controlled_text(result, default_width=21, notation='z'), result)

    def test_story_corpus_uses_only_z_scopes(self):
        for path in STORY_FILES:
            for entry in json.loads(path.read_text(encoding='utf-8'))['entries']:
                text = entry.get('translation') or ''
                self.assertNotRegex(text, r'<(?:width|space):', f'{path.name}:{entry.get("id")}')
                expand(text)


if __name__ == '__main__':
    unittest.main()
