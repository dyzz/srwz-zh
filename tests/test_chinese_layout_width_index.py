"""The indexed slice width used by the layout search must equal the direct sum."""
import random
import sys
import unittest
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from srwz.chinese_layout import LayoutToken, _occupied_width, _occupied_width_index, tokenize_dialogue
from srwz.renderer_metrics import compact_visible_runs


class OccupiedWidthIndexTests(unittest.TestCase):
    def assert_matches_direct(self, tokens):
        width = _occupied_width_index(tokens)
        for start in range(len(tokens) + 1):
            for end in range(start, len(tokens) + 1):
                self.assertEqual(width(start, end), _occupied_width(tokens[start:end]), (start, end))

    def test_random_fractional_advances_and_overhangs(self):
        rng = random.Random(20261007)
        for _ in range(500):
            tokens = [
                LayoutToken('名', Fraction(rng.randint(0, 30), rng.choice((1, 11, 12, 22))),
                            overhang=Fraction(rng.randint(0, 8), rng.choice((1, 11, 22)))
                            if rng.random() < 0.4 else Fraction(0))
                for _ in range(rng.randint(0, 40))
            ]
            self.assert_matches_direct(tokens)

    def test_controlled_library_body_tokens(self):
        tagged = compact_visible_runs('甲' * 12 + 'Dove一起帮助贝克越狱，150吨的握力。99%完成。',
                                      default_advance_px=22)
        tokens = tokenize_dialogue('<width:16><space:16>' + tagged, default_advance_px=22)
        self.assertTrue(any(token.overhang for token in tokens))
        self.assert_matches_direct(tokens)


if __name__ == '__main__':
    unittest.main()
