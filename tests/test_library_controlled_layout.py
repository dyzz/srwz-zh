"""LIBRARY capacity fallback must preserve controlled text and surface metrics."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from build_library_v02_component import reflow_body,reflow_body_legacy
from srwz.library import LibraryScopeError
from srwz.renderer_metrics import compact_visible_runs,text_extent
from srwz.text import CONTROL_NOTATION


class LibraryControlledLayoutTests(unittest.TestCase):
    def test_numeric_prose_fits_with_22_pixel_body_restore(self):
        tagged=compact_visible_runs('甲'*12+'150吨的握力。',default_advance_px=22)
        result,widths=reflow_body(tagged,16)
        self.assertEqual(result.replace('\n',''),'<width:16><space:16>'+tagged)
        self.assertIn('150吨',CONTROL_NOTATION.sub('',result).splitlines()[0])
        self.assertTrue(all(w<=16 for w in widths))
        self.assertTrue(all(text_extent(line,default_advance_px=22).occupied_px<=16*22 for line in result.splitlines()))

    def test_capacity_fallback_cannot_split_controlled_scopes(self):
        tagged=compact_visible_runs('甲'*12+'Dove一起帮助贝克越狱。',default_advance_px=22)
        self.assertEqual(reflow_body_legacy(tagged,16),reflow_body(tagged,16))
        scope=compact_visible_runs('A'*40,default_advance_px=22)
        for renderer in (reflow_body,reflow_body_legacy):
            with self.assertRaises(LibraryScopeError):renderer(scope,16)

    def test_percent_restore_and_following_chinese_survive_fallback(self):
        tagged=compact_visible_runs('甲'*13+'99%完成，中文保持原宽。',default_advance_px=22)
        result,widths=reflow_body_legacy(tagged,16)
        self.assertEqual(result.replace('\n',''),'<width:16><space:16>'+tagged)
        self.assertIn('99%<space:16><width:16>',result)
        self.assertTrue(all(w<=16 for w in widths))

    def test_capacity_fallback_retains_protected_mixed_names(self):
        tagged=compact_visible_runs('甲'*13+'013特别小队前来支援。',default_advance_px=22)
        result,_=reflow_body_legacy(tagged,16,protected_terms=('013特别小队',))
        self.assertTrue(any('013特别小队' in CONTROL_NOTATION.sub('',line) for line in result.splitlines()))


if __name__=='__main__':unittest.main()
