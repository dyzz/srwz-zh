import unittest

from tools.apply_confirmed_story_terms import transform_translation


class ApplyConfirmedStoryTermsTests(unittest.TestCase):
    def test_distinguishes_gallia_mecha_from_galia_continent(self):
        revised, rules = transform_translation("ギャリアで行く", "加利亚出击")
        self.assertEqual(revised, "伽利亚出击")
        self.assertEqual(rules, ("gallia",))

        unchanged, rules = transform_translation("ガリア大陸へ行く", "前往加利亚大陆")
        self.assertEqual(unchanged, "前往加利亚大陆")
        self.assertEqual(rules, ())

    def test_distinguishes_ji_edel_from_edel_bernal(self):
        revised, _ = transform_translation(
            "ジ・エーデル・ベルナルだよ！",
            "其名为The·艾黛尔·贝尔纳尔！",
        )
        self.assertEqual(revised, "其名为极·艾岱尔·贝鲁那尔！")

        revised, _ = transform_translation("ジ・エーデル！", "吉·艾德尔！")
        self.assertEqual(revised, "极·艾岱尔！")

        unchanged, rules = transform_translation(
            "エーデル・ベルナル准将",
            "艾黛尔·贝尔纳尔准将",
        )
        self.assertEqual(unchanged, "艾黛尔·贝尔纳尔准将")
        self.assertEqual(rules, ())

    def test_applies_wm_and_ergo_compounds(self):
        revised, _ = transform_translation(
            "ウォーカーマシンを動かせ",
            "让Walker Machine前进",
        )
        self.assertEqual(revised, "让WM前进")

        revised, _ = transform_translation("エルゴブレイク！！", "Ergo Break！！")
        self.assertEqual(revised, "工学分解！！")

        revised, _ = transform_translation("エルゴの戦士達", "艾尔戈的战士们")
        self.assertEqual(revised, "工学战士们")

    def test_combined_ji_edel_and_the_end_line(self):
        revised, rules = transform_translation(
            "こいつでジ・エンドだ！　\\n　ジ・エーデル！！",
            "“这就是尼尔瓦修 the END！\\n　吉·艾黛尔！！”",
        )
        self.assertEqual(revised, "“这就是尼尔瓦修终式！\\n　极·艾岱尔！！”")
        self.assertEqual(rules, ("ji-edel", "the-end"))


if __name__ == "__main__":
    unittest.main()
