"""SP detail prose respects the runtime panel, independently of HSFC slots."""
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'tools/special_disc/writeback')]
from write_frame_text import flow_synopsis, FLOW_PROTECTED_TERMS, validate_flow_layout


class SpFlowLayoutTests(unittest.TestCase):
    def test_orphan_tail_is_reflowed_without_rewriting(self):
        text='　罗杰与万丈讲起在贝尔弗莱斯特遇见兰顿的祖父阿克塞尔时的往事。'
        lines=flow_synopsis(text).splitlines()
        self.assertEqual(''.join(lines),text)
        self.assertGreaterEqual(len(lines[-1]),8)
        self.assertTrue(any('往事' in line for line in lines))
        self.assertTrue(any('阿克塞尔' in line for line in lines))
        self.assertTrue(any('贝尔弗莱斯特' in line for line in lines))
        self.assertTrue(all(len(line)<=29 for line in lines))

    def test_configured_terms_survive_wrap_boundaries(self):
        for term in FLOW_PROTECTED_TERMS:
            text='　'+'甲'*22+term+'乙'*12+'。'
            result=flow_synopsis(text)
            self.assertEqual(result.replace('\n',''),text)
            self.assertTrue(any(term in line for line in result.splitlines()),term)

    def test_toshiya_is_a_complete_person_name(self):
        text='　来袭的伊尔塔正是利用这份设计图，掌握了巨神Σ的弱点。斗志也因此陷入绝境，理惠却奋不顾身地救下了他。'
        lines=flow_synopsis(text).splitlines()
        self.assertEqual(''.join(lines),text)
        self.assertTrue(any('斗志也' in line for line in lines))
        self.assertFalse(any(line.endswith('斗志') for line in lines))

    def test_detail_allows_eleven_lines_but_rejects_invisible_twelfth(self):
        text='\n'.join(['　完整保留这一段。']*11)
        self.assertEqual(flow_synopsis(text),text)
        with self.assertRaisesRegex(ValueError,'12/11'):
            flow_synopsis(text+'\n　这一段不能消失。')

    def test_readback_rejects_a_split_person_name(self):
        with self.assertRaisesRegex(ValueError,'斗志也'):
            validate_flow_layout('斗志\n也因此陷入绝境。')

    def test_term_boundary_and_paragraph_indentation(self):
        text='　高安为了自己的目的调查黑历史，将采掘者希德派往加利亚大陆，又委托约瑟夫调查附近的环形山。\n　然而，他们踏入的却是名为失落山脉的禁忌之地。'
        result=flow_synopsis(text)
        self.assertEqual(result.replace('\n',''),text.replace('\n',''))
        self.assertTrue(any('加利亚大陆' in line for line in result.splitlines()))
        self.assertEqual(sum(line.startswith('　') for line in result.splitlines()),2)


if __name__=='__main__':unittest.main()
