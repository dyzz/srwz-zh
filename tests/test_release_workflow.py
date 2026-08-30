from __future__ import annotations

import base64
import hashlib
import json
import struct
import unittest
import zlib
from pathlib import Path

from tools.build_full_story_components import (
    ALL_COMPONENT_MEMBERS,
    COMPONENT_BUILD_GROUPS,
)
from tools.editorial_review.apply_confirmed_z2_shared_terms import (
    FEI_PERSON_SOURCE_IDS,
)
from tools.srwz.title_menu import (
    RAMP_LEVEL_COUNT,
    SELECTED_RAMP_BASE,
    TITLE_LABEL_HEIGHT,
    TITLE_LABEL_WIDTH,
    TITLE_TEXTURE_HEIGHT,
    TITLE_TEXTURE_WIDTH,
    UNSELECTED_RAMP_BASE,
    apply_title_menu_masks,
)
from tools.srwz.stage import STAGE_BASE_ADDRESS
from tools.srwz.stage_formations import _scan_packed8_groups
from tools.srwz.text import encode_text, load_text_table
from tools.srwz.release_font import (
    audit_entry_font,
    baseline_with_protected_original_glyphs,
)
from tools.srwz.release_font_policy import (
    DEFAULT_WIDTH_CLASS,
    allocation_width_class,
)
from tools.srwz.font import GLYPH_SIZE, standard_glyph_index
from tools.srwz.chinese_layout import (
    dialogue_line_widths,
    fit_chinese_dialogue_layout,
    logical_dialogue_text,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load(relative: str) -> dict:
    return json.loads((PROJECT_ROOT / relative).read_text(encoding="utf-8"))


def _mapping_sha256(assignments: list[dict]) -> str:
    rows = sorted(
        (item["character"], item["code"], item["glyph_index"])
        for item in assignments
    )
    return hashlib.sha256(
        json.dumps(
            rows,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


class ReleaseWorkflowTest(unittest.TestCase):
    def test_dialogue_layout_reflows_without_shortening_text(self) -> None:
        source = "“我们也对迪兰达尔议长的所作所为心存疑虑。”"
        fitted = fit_chinese_dialogue_layout(source)
        self.assertEqual(fitted.preserved_reason, "reflowed_to_fit")
        self.assertEqual(
            logical_dialogue_text(fitted.text),
            logical_dialogue_text(source),
        )
        self.assertLessEqual(len(fitted.line_widths), 3)
        self.assertLessEqual(max(fitted.line_widths), 21)

    def test_dialogue_layout_preserves_valid_manual_breaks(self) -> None:
        source = "“第一行。”\n　第二行。”"
        fitted = fit_chinese_dialogue_layout(source)
        self.assertEqual(fitted.preserved_reason, "already_fits")
        self.assertEqual(fitted.text, source)
        self.assertEqual(fitted.line_widths, dialogue_line_widths(source))

    def test_protected_stock_punctuation_is_valid_localized_text(self) -> None:
        class Table:
            inverse_characters = {"」": 0x8176}
            characters = {0x8176: "」"}

        baseline = {
            "table": Table(),
            "extended_entries": (),
            "font": b"\x01" * (
                (standard_glyph_index(0x8176) + 1) * GLYPH_SIZE
            ),
            "base_assignments": {},
            "proposal_assignments": {},
        }
        protected = baseline_with_protected_original_glyphs(
            baseline,
            {
                "protected_source_characters": "」",
                "protected_original_codes": ["8176"],
            },
        )
        coverage = audit_entry_font(
            [{"id": "bazaar", "translation": "」"}],
            protected,
        )
        self.assertEqual(coverage["missing_character_count"], 0)
        self.assertEqual(coverage["original_font_visible_character_count"], 0)
        self.assertEqual(coverage["selected_font_visible_character_count"], 1)

    def test_v030_044_missing_glyphs_use_unique_default_width_slots(self) -> None:
        snapshot = _load("config/encoding/zh-release-font-assignments.json")
        expected = {
            "齑": ("9670", 4080),
            "糗": ("9674", 4084),
            "犊": ("9675", 4085),
            "阎": ("9678", 4088),
            "黾": ("9689", 4105),
            "锄": ("968A", 4106),
            "剿": ("968F", 4111),
            "噫": ("9690", 4112),
            "欸": ("9691", 4113),
        }
        rows = {
            row["character"]: row
            for row in snapshot["primary_assignments"]
            if row["character"] in expected
        }
        self.assertEqual(
            {
                character: (row["code"], row["glyph_index"])
                for character, row in rows.items()
            },
            expected,
        )
        self.assertTrue(
            all(
                row["allocation_width_class"] == DEFAULT_WIDTH_CLASS
                and allocation_width_class(int(row["code"], 16))
                == DEFAULT_WIDTH_CLASS
                for row in rows.values()
            )
        )
        self.assertEqual(len({row["code"] for row in rows.values()}), 9)
        self.assertEqual(len({row["glyph_index"] for row in rows.values()}), 9)
        remaining_codes = {
            row["code"] for row in snapshot["remaining_allocation_candidates"]
        }
        self.assertTrue(
            remaining_codes.isdisjoint(
                expected_code for expected_code, _ in expected.values()
            )
        )

    def test_bazaar_confirmation_fragments_keep_corner_brackets(self) -> None:
        remaining = _load("corpus/zh/menu/remaining-ui.json")
        fragments = remaining["slps_context_ui_by_offset"]
        self.assertEqual(fragments["0x33DA60"], "」将被购买。")
        self.assertEqual(fragments["0x33DA98"], "」售　")

    def test_v030_039_stage_107_feedback_decisions(self) -> None:
        stage = _load("corpus/zh/story-dialogue/stage-107.json")
        translations = {
            entry["id"]: entry["translation"] for entry in stage["entries"]
        }
        expected = {
            "story/107/dialogue/02.03/0054": (
                "“然后，我一直惦记着你……\n"
                "一直想为那天的事跟你说声对不起……”"
            ),
            "story/107/dialogue/02.03/0091": (
                "“然后，我一直惦记着你……\n"
                "　一直想为那时的事跟你说声对不起……”"
            ),
            "story/107/dialogue/02.03/0053": (
                "“胜平……胜平……我被外星人追杀，落到了他们手里，\n"
                "眼睁睁看着好多人死掉”"
            ),
            "story/107/dialogue/02.03/0090": (
                "“胜平……我被外星人追捕，落到了他们手里，\n"
                "　眼睁睁看着好多人死掉”"
            ),
            "story/107/dialogue/01.26/0007": (
                "“就靠巨大的身躯撞过去，\n"
                "　连同亚空间护盾一起碾碎……！”"
            ),
            "story/107/dialogue/01.26/0002": (
                "“是亚空间力场……！\n"
                "　人工太阳正利用能量扭曲着周围的时空！”"
            ),
            "story/107/dialogue/01.69/0002": (
                "“是亚空间力场……！\n"
                "　人工太阳正利用过剩的能量扭曲着周围的时空！”"
            ),
            "story/107/dialogue/01.25/0000": (
                "“这样磨磨蹭蹭地打下去，什么时候才是个头！”"
            ),
            "story/107/dialogue/01.84/0002": (
                "“迪拉尔是个堂堂正正战斗的男子汉！\n"
                "　你和他比差得远呢！”"
            ),
            "story/107/dialogue/01.16/0026": "“看来小菲果然是个好孩子呢。”",
            "story/107/dialogue/01.17/0026": "“看来小菲果然是个好孩子呢。”",
            "story/107/dialogue/01.06/0021": (
                "“各位，请抓紧了！我们的逃脱地点就在那里！”"
            ),
        }
        self.assertEqual(
            {entry_id: translations[entry_id] for entry_id in expected},
            expected,
        )

    def test_v030_041_stage_001_tieba_floor_320_decisions(self) -> None:
        stage = _load("corpus/zh/story-dialogue/stage-001.json")
        translations = {
            entry["id"]: entry["translation"] for entry in stage["entries"]
        }
        expected = {
            "story/001/dialogue/02.01/0012": (
                "“哼……看你那副害怕的样子……\n"
                "　看来你很清楚我们是谁啊”"
            ),
            "story/001/dialogue/02.01/0017": (
                "“果然，这帮家伙还是更适合‘玩娃娃’”"
            ),
            "story/001/dialogue/02.01/0036": (
                "“我们重要的新人被人找茬，\n"
                "　我怎么能干看着”"
            ),
            "story/001/dialogue/02.01/0124": (
                "“……那就别着急。\n"
                "　人嘛，从自己力所能及的事做起就行了”"
            ),
        }
        self.assertEqual(
            {entry_id: translations[entry_id] for entry_id in expected},
            expected,
        )

    def test_v030_043_site_feedback_priority_decisions(self) -> None:
        translations = {}
        for stage_index in (13, 14, 15, 16, 17, 108):
            stage = _load(
                f"corpus/zh/story-dialogue/stage-{stage_index:03d}.json"
            )
            translations.update(
                {entry["id"]: entry["translation"] for entry in stage["entries"]}
            )

        expected = {
            "story/013/dialogue/01.03/0007": (
                "“第两次、你还敢叫这个名是吧！”"
            ),
            "story/013/dialogue/01.13/0009": (
                "“我要把你大解体！连螺丝都拆个稀碎！！”"
            ),
            "story/014/dialogue/01.03/0001": (
                "“$n！别兴奋过头一下\n"
                "　打到穹顶都市上嗷！”"
            ),
            "story/014/dialogue/02.02/0076": (
                "“总之，停下脚步很危险。\n"
                "　只能糊弄糊弄边移动边修理了……”"
            ),
            "story/015/dialogue/01.19/0003": (
                "“$n，梅尔！\n"
                "　钢铁齿轮，刚刚到达！”"
            ),
            "story/015/dialogue/02.02/0059": "“……跟我无关啊…”",
            "story/016/dialogue/01.16/0008": (
                "“我要干…！我干的成！！把所有妨碍我的家伙干掉，"
                "让他们承认我的力量！！”"
            ),
            "story/017/dialogue/01.05/0003": (
                "“真是的！别刚到被弹过来的地方就别拿出噼里啪啦的"
                "东西啊，混蛋！”"
            ),
            "story/108/dialogue/02.01/0035": (
                "“大致情况我了解。\n"
                "但这件事，应该直接去问奎因斯坦博士本人。”"
            ),
            "story/108/dialogue/02.01/0100": (
                "“那时，S-1星人应该是在那场时空震动中被卷入，\n"
                "跨越了时间，才抵达这个多元世界的吧。”"
            ),
            "story/108/dialogue/02.01/0320": (
                "“我们伊诺森特应用那项技术，\n"
                "创造了生存在佐拉大地上的新人类，也就是平民。”"
            ),
            "story/108/dialogue/02.02/0072": (
                "“只是不断倾倒些无聊的拖延话术，\n"
                "　浪费时间而已。……你其实早就明白了吧？”"
            ),
            "story/108/dialogue/02.02/0073": (
                "“大众根本就不在乎什么真相。大众不会因为真相而采取行动。\n"
                "他们需要的，是足够响亮的呼声和强烈的刺激！”"
            ),
        }
        self.assertEqual(
            {entry_id: translations[entry_id] for entry_id in expected},
            expected,
        )

    def test_v030_043_remaining_site_feedback_adjustments(self) -> None:
        battle = _load("corpus/zh/battle/srvc-lines.json")
        battle_translations = {
            entry["id"]: entry["translation"] for entry in battle["entries"]
        }
        battle_expected = {
            "battle:24510": "“切换——波塞冬！！\\n　启动！！”",
            "battle:24481": "“毕竟是对上我的狮虎，没办法啊。”",
            "battle:22668": "“你对上了兜甲儿！”",
            "battle:22157": "“先拿你开始血祭！”",
            "battle:24663": "“你吃奶的劲也打不倒我哦？\\n　呼呼呼呼…”",
            "battle:24648": "“比亚路星人的遗产，\\n　我要全部化为齑粉！”",
            "battle:24642": "“杰利……你这毛头小子\\n　休想超越老夫…！”",
            "battle:24640": "“说到底，你只是人类之敌。\\n　呼呼呼呼呼…！”",
            "battle:24626": "“别碍老夫的事啊啊啊！”",
            "battle:24247": "“可恶！真是出大糗了！”",
            "battle:24110": "“看好，给你们开开眼！”",
            "battle:18104": "“阿芙罗蒂亚！\\n　看那片蓝色大海，你难道毫无反应吗！？”",
            "battle:18092": "“闭上你那张臭嘴！”",
            "battle:18085": "“就算是你们，敢妨碍我们的话…！”",
            "battle:18064": "“上了，你们两个！”",
            "battle:02138": "“那厮由我！”",
            "battle:02128": "“这次必打倒你！”",
            "battle:00819": "“现在！”",
            "battle:25088": "“还没完！见识我们全部力量吧！”",
            "battle:24527": "“把所有谜团都吐出来！！”",
            "battle:24423": "“让你见识什么叫实力差距！”",
            "battle:01703": "“太天真！”",
            "battle:18243": "“觉悟吧，布莱大帝！”",
            "battle:18242": "“希德拉元帅，休想逃！”",
            "battle:18241": "“我饶不了你，希德拉元帅！”",
            "battle:18203": "“瞄准首轮攻击制造的破绽……！”",
            "battle:24542": "“我定杀你！”",
            "battle:22662": "“剩口气我也要打倒你！”",
            "battle:07343": "“见识下我们的力量！”",
            "battle:21949": "“月到头，运也到头……了吗！？”",
            "battle:22015": "“哈哈哈！去死吧！”",
            "battle:22014": "“去死！”",
            "battle:22020": "“你的勇气不管用！”",
            "battle:22033": "“古连泰沙！见阎王去吧！”",
            "battle:22052": "“哈哈哈！拿你血祭！”",
            "battle:22067": "“天真，太天真！”",
            "battle:22101": "“该死，这是什么力量！”",
            "battle:05279": "“那家伙是我对手！”",
            "battle:23209": "“让你见识机械铁甲鬼的力量！”",
        }
        self.assertEqual(
            {
                entry_id: battle_translations[entry_id]
                for entry_id in battle_expected
            },
            battle_expected,
        )

        story_translations = {}
        for stage_index in (13, 16, 108):
            stage = _load(
                f"corpus/zh/story-dialogue/stage-{stage_index:03d}.json"
            )
            story_translations.update(
                {entry["id"]: entry["translation"] for entry in stage["entries"]}
            )
        story_expected = {
            "story/108/dialogue/02.01/0175": (
                "“……关于疑似阿瑟·兰克那人的所在地，已经有了线索。”"
            ),
            "story/016/dialogue/01.15/0004": "“你、你他妈扯什么犊子！”",
            "story/013/dialogue/01.02/0003": (
                "“啊～啊～……现在正在测试麦克风。今天\n"
                "　是个晴天……水黾好红啊，啊伊乌诶哦……”"
            ),
            "story/108/dialogue/02.01/0058": (
                "“对！锄强扶弱，以勇气为伴对抗巨大邪恶！\n"
                "那正是男人的浪漫！”"
            ),
            "story/108/dialogue/01.09/0003": (
                "“是飞・心露啊。\n"
                "我可没心情看你个逃兵现在在这儿摆长官架子……！”"
            ),
            "story/108/dialogue/02.01/0059": (
                "“我爱超级机器人，就像爱纳豆和牛丼一样！\n"
                "　我会连同飞队长和伙伴们一起，拼上性命去战斗！”"
            ),
        }
        self.assertEqual(
            {
                entry_id: story_translations[entry_id]
                for entry_id in story_expected
            },
            story_expected,
        )

    def test_v030_042_escape_wording_is_context_bound(self) -> None:
        story_expected = {
            "story/028/dialogue/01.14/0010": (
                "“但今天也不一定是友军。\n　桂，回格罗玛！趁现在逃离吧！”"
            ),
            "story/031/dialogue/02.01/0078": (
                "“……被黑色夹住的棋子会翻过来变成黑色。\n"
                "　迅速撤离，密涅瓦…………这是谁给的？”"
            ),
            "story/032/dialogue/01.12/0004": "“本舰将突破敌方防卫部队，撤离奥布！”",
            "story/032/dialogue/01.18/0001": "“引擎最大出力！趁现在撤离奥布！”",
            "story/032/dialogue/02.03/0051": (
                "“和平号也归航了。但是，\n　撤离奥布的大天使号依然下落不明。”"
            ),
            "story/032/dialogue/02.03/0117": (
                "“彼此彼此。撤离奥布后的战斗表现，\n　议长也很满意。”"
            ),
            "story/032/dialogue/02.03/0160": (
                "“彼此彼此。撤离奥布后的战斗表现，\n　议长也很满意。”"
            ),
            "story/036/dialogue/01.37/0001": "“哼！命更重要！快逃生！！”",
            "story/043/dialogue/01.33/0000": (
                "“可恶啊啊啊！结果到最后还是一直输！\n　干不下去了！逃生！！”"
            ),
            "story/043/dialogue/01.34/0000": (
                "“我、我可是坚持到最后了！\n　相信评分不会降低！逃生！！”"
            ),
            "story/043/dialogue/01.35/0000": (
                "“我、我要写调职申请，\n　离开西伯利亚！逃生！”"
            ),
            "story/048/dialogue/01.27/0010": "“逃吧，独眼鬼！至少我们得逃出去！”",
            "story/055/dialogue/01.13/0004": (
                "“户高一佐，我们逃吧！\n　不管用什么手段，我都要把他贬职！”"
            ),
            "story/055/dialogue/01.13/0012": "“我、我不知道！随你便！我要逃了！”",
            "story/083/dialogue/01.20/0004": "“快逃生，师父！那台机体撑不住了！”",
            "story/107/dialogue/01.09/0001": "“就这样逃出去！”",
            "story/108/dialogue/01.17/0004": (
                "“撤离吧，吉布利尔！\n　继续战斗只会让情况更糟！”"
            ),
            "story/108/dialogue/01.17/0005": "“但、但是！就算撤离，又能去哪里！？”",
            "story/108/dialogue/01.20/0000": "“本机已经到极限了！逃生后从地面指挥！”",
            "story/108/dialogue/02.01/0005": (
                "“……我拒绝了逃生……\n　应该就这样被击坠了才对……”"
            ),
            "story/108/dialogue/02.02/0024": "“我去追诺尔布！吉隆，你先逃出去！！”",
            "story/112/dialogue/01.13/0000": "“唔哦哦哦哦！古拉博士，快逃！”",
            "story/112/dialogue/01.13/0002": (
                "“博士还有完成时空控制装置的重任！\n　这里交给我，您快逃！！”"
            ),
            "story/118/dialogue/01.38/0000": "“咕哦哦哦！弹射逃生！！”",
            "story/128/dialogue/01.39/0000": "“唔哦哦哦！古拉博士，快逃！”",
            "story/128/dialogue/01.39/0005": (
                "“来吧，古拉博士！这里交给我，您快逃！！”"
            ),
            "story/138/dialogue/01.91/0000": "“住手吧，雷！快弹射逃生！”",
            "story/138/dialogue/01.168/0000": "“住手吧，雷！快弹射逃生！”",
            "story/139/dialogue/02.01/0082": (
                "“我和阿斯兰都错了很多次……\n"
                "　逃离奥布后的战斗，也绝不能说正确……”"
            ),
            "story/141/dialogue/01.05/0003": (
                "“全员，准备撤离！事已至此，\n"
                "　就算用本舰撞上去，也要打倒他！”"
            ),
            "story/146/dialogue/01.05/0003": (
                "“全员，准备撤离！事已至此，\n"
                "　就算用本舰撞上去，也要打倒他！”"
            ),
        }
        story_actual = {}
        for stage_number in {
            entry_id.split("/")[1] for entry_id in story_expected
        }:
            stage = _load(f"corpus/zh/story-dialogue/stage-{stage_number}.json")
            story_actual.update(
                {entry["id"]: entry["translation"] for entry in stage["entries"]}
            )
        self.assertEqual(len(story_expected), 31)
        self.assertEqual(
            {entry_id: story_actual[entry_id] for entry_id in story_expected},
            story_expected,
        )

        stage_004 = _load("corpus/zh/story-dialogue/stage-004.json")
        stage_004_translations = {
            entry["id"]: entry["translation"] for entry in stage_004["entries"]
        }
        self.assertEqual(
            stage_004_translations["story/004/dialogue/01.31/0001"],
            "“爱玛中尉……顺利撤离了吗……”",
        )

        battle_expected = {
            "battle:00113": "“可恶！逃生！”",
            "battle:02429": "“到此为止了吗！逃生！！”",
            "battle:02505": "“可恶，不行吗！逃生！”",
            "battle:03190": "“快、快逃生！！”",
            "battle:03194": "“全员撤离！！”",
            "battle:03704": "“快、快逃生！”",
            "battle:04049": "“超出极限了吗！我要逃生！”",
            "battle:05241": "“可恶…逃生！！”",
            "battle:06192": "“呃啊啊啊啊啊！！\\n　得逃生…得逃生才行！”",
            "battle:07179": "“超出极限！逃生！！”",
            "battle:07595": "“啊啊…！全员撤离！”",
            "battle:07598": "“全员，以防万一做好撤离准备！”",
            "battle:07771": "“啊啊！快、快逃生！”",
            "battle:08443": "“这下完了！逃生！”",
            "battle:08965": "“唔……逃生！”",
            "battle:09563": "“不行！快逃生！！”",
            "battle:09600": "“逃生！后面就拜托了！”",
            "battle:10564": "“不行！得逃生！”",
            "battle:10999": "“被干掉了吗…！得逃生！”",
            "battle:12039": "“呃啊啊！\\n　不、不行了！我要逃生！”",
            "battle:13080": "“全员撤离！”",
            "battle:13109": "“逃、逃生！”",
            "battle:13114": "“只能逃生了！”",
            "battle:13762": "“呃…到此为止了吗！\\n　星1号，逃生！”",
            "battle:14208": "“糟了，快逃生！”",
            "battle:15177": "“我、我要逃生了！”",
            "battle:16113": "“小的们，快逃生！”",
            "battle:16444": "“不、不行了～！逃生！！”",
            "battle:16672": "“被打中了！？快逃生！！”",
            "battle:18408": "“准、准备逃生！\\n　先确保我的安全！”",
            "battle:19690": "“收拾好行李，梅尔！\\n　情况不妙就逃！”",
            "battle:19702": "“快逃，梅尔！\\n　别忘了值钱的东西！！！”",
            "battle:20447": "“任务失败……！逃生！”",
            "battle:21390": "“多萝西，万一的时候你就先逃！”",
            "battle:21397": "“不必多说。逃生吧。”",
            "battle:21605": "“逃生！\\n　不能在这里被打倒！”",
            "battle:21743": "“呃！逃生！！”",
            "battle:22355": "“多谢款待。…逃出来了吧？”",
            "battle:23573": "“战斗不能！大家快逃生！”",
            "battle:24244": "“可、可恶！逃生！”",
            "battle:24888": "“哇啊！？快、快逃生…！！”",
        }
        battle = _load("corpus/zh/battle/srvc-lines.json")
        battle_actual = {
            entry["id"]: entry["translation"] for entry in battle["entries"]
        }
        self.assertEqual(len(battle_expected), 41)
        self.assertEqual(
            {entry_id: battle_actual[entry_id] for entry_id in battle_expected},
            battle_expected,
        )
        self.assertEqual(
            battle_actual["battle:19220"],
            "“不能让他们送命！\\n　下令撤退！”",
        )

    def test_chapter_intertitles_keep_linear_index_storage(self) -> None:
        corpus = _load("corpus/zh/chapter-intertitles.json")
        self.assertEqual(
            corpus["render"]["storage_layout"],
            "linear_row_major_despite_psmt8_header",
        )
        self.assertEqual(
            corpus["visible_japanese_text_chunk_indices"],
            [21, 22],
        )
        for entry in corpus["entries"]:
            self.assertIn("source_linear_indexes_sha256", entry)
            self.assertIn("output_linear_indexes_sha256", entry)
            self.assertNotIn("source_logical_indexes_sha256", entry)
            self.assertNotIn("output_logical_indexes_sha256", entry)

    def test_short_formation_table_requires_its_owner_record(self) -> None:
        table = load_text_table(
            PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
        )
        source = "ファクトリー"
        text_offset = 64
        encoded = encode_text(source, table, terminate=True)
        data = bytearray(96)
        data[text_offset : text_offset + len(encoded)] = encoded

        self.assertEqual(
            _scan_packed8_groups(
                bytes(data),
                table,
                stage_index=23,
                source_texts=frozenset({source}),
            ),
            (),
        )

        # The 32-byte formation owner places its name pointer at byte 16.
        data[8:10] = b"\xFF\xFF"
        data[14:16] = b"\xFF\xFF"
        struct.pack_into("<I", data, 16, STAGE_BASE_ADDRESS + text_offset)
        struct.pack_into("<I", data, 20, 0xFF)
        groups = _scan_packed8_groups(
            bytes(data),
            table,
            stage_index=23,
            source_texts=frozenset({source}),
        )
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].layout, "pointer8-16")
        self.assertEqual(
            [(cell.offset, cell.source_text) for cell in groups[0].cells],
            [(text_offset, source)],
        )

    def test_formation_inventory_covers_all_26_new_owned_slots(self) -> None:
        corpus = _load("corpus/zh/menu/stage-default-formations.json")
        terms = corpus["translations_by_source_text"]
        self.assertEqual(len(terms), 256)
        self.assertEqual(terms["エゥーゴ１"], "奥古1")
        self.assertEqual(terms["アイアン・ギアー組"], "钢铁齿轮组")
        self.assertEqual(terms["アーサー親衛隊"], "阿瑟亲卫队")
        self.assertEqual(terms["ソレイユ（味方）"], "太阳号（我方）")
        self.assertEqual(terms["修理屋"], "修理工")
        self.assertEqual(terms["ガウリ隊"], "高富利队")

        inventory = _load("config/stage-default-formation-inventory.json")
        self.assertEqual(
            inventory["expected"],
            {
                "entry_count": 11424,
                "group_count": 828,
                "inventory_sha256": (
                    "32e53fa9b14fc39f41f4e08218e90585413f2dce5dd76ac203ce2c36ede9f013"
                ),
                "stage_count": 179,
                "unique_source_count": 256,
            },
        )

        sources = inventory["sources"]
        positions = {
            (group["stage_index"], offset): (sources[source_index], group["layout"])
            for group in inventory["groups"]
            for offset, source_index in group["cells"]
        }
        expected = {
            (9, 0xCF78): ("エゥーゴ２", "packed8-16"),
            (9, 0xCFA0): ("エゥーゴ１", "packed8-16"),
            (10, 0x15AA8): ("エゥーゴ１", "packed8-16"),
            (10, 0x15AB8): ("エゥーゴ２", "packed8-16"),
            (23, 0x7E10): ("ファクトリー", "pointer8-16"),
            (28, 0x1C8B8): ("グローマ隊", "packed8-16"),
            (28, 0x1C9C8): ("エクソダス組", "packed8-16"),
            (29, 0x13B68): ("　ゴッドシグマ", "packed8-24"),
            (31, 0xC510): ("カラバ", "pointer8-8"),
            (62, 0xD780): ("キング・ビアル", "pointer8-16"),
            (62, 0xD790): ("ゴッドシグマ", "pointer8-16"),
            (64, 0xA700): ("グランナイツ", "pointer8-16"),
            (65, 0xD158): ("キング・ビアル", "pointer8-16"),
            (65, 0xD168): ("グランナイツ", "pointer8-16"),
            (107, 0x25F30): ("アイアン・ギアー組", "packed8-32"),
            (108, 0x1BE40): ("アイアン・ギアー組", "packed8-32"),
            (108, 0x1BE78): ("アーサー親衛隊", "packed8-16"),
            (124, 0x17F0): ("フリーデン隊", "pointer8-16"),
            (137, 0x6F00): ("ソレイユ（味方）", "packed8-24"),
            (140, 0x1F2D8): ("ネゴシエイター", "pointer8-16"),
            (145, 0x18C40): ("ソレイユ（味方）", "packed8-32"),
            (159, 0xD10): ("ザンボット３", "pointer8-16"),
            (162, 0xA90): ("バルディオス", "pointer8-16"),
            (166, 0x1010): ("ニルヴァーシュ", "pointer8-16"),
            (169, 0x1D78): ("アクエリオン", "pointer8-16"),
            (170, 0x1CF8): ("アクエリオン", "pointer8-16"),
        }
        self.assertEqual(
            {position: positions.get(position) for position in expected},
            expected,
        )
        # This is runtime-keyword row 19, not a formation owner.
        self.assertNotIn((95, 0x106C8), positions)

    def test_gowri_name_is_consistent_across_current_corpus(self) -> None:
        glossary = _load("corpus/glossary/story-speakers-v1.json")
        entry = next(
            item
            for item in glossary["terms"]
            if item["id"] == "people/speaker-980ee4d20d74"
        )
        self.assertEqual(entry["translation"], "高富利")
        self.assertIn("高富力", entry["deprecated_translations"])

        stale_paths = [
            path.relative_to(PROJECT_ROOT).as_posix()
            for path in (PROJECT_ROOT / "corpus" / "zh").rglob("*.json")
            if "高富力" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(stale_paths, [])

    def test_latest_person_names_propagate_through_active_text(self) -> None:
        corpus_paths = sorted((PROJECT_ROOT / "corpus" / "zh").rglob("*.json"))
        stale_unambiguous = (
            "贝洛",
            "辛西娅",
            "亚蒂特",
            "高利",
            "继美",
            "塔荷",
            "菲伊",
            "菲·辛路",
            "菲・辛路",
            "菲·辛露",
            "菲・辛露",
            "菲·新路",
        )
        stale_paths = {
            stale: [
                path.relative_to(PROJECT_ROOT).as_posix()
                for path in corpus_paths
                if stale in path.read_text(encoding="utf-8")
            ]
            for stale in stale_unambiguous
        }
        self.assertEqual(stale_paths, {stale: [] for stale in stale_unambiguous})

        entries: dict[str, dict] = {}
        for path in corpus_paths:
            document = json.loads(path.read_text(encoding="utf-8"))

            def collect(node: object) -> None:
                if isinstance(node, dict):
                    entry_id = node.get("id")
                    if isinstance(entry_id, str):
                        entries[entry_id] = node
                    for value in node.values():
                        collect(value)
                elif isinstance(node, list):
                    for value in node:
                        collect(value)

            collect(document)

        missing = sorted(set(FEI_PERSON_SOURCE_IDS) - set(entries))
        stale_fei = sorted(
            entry_id
            for entry_id in FEI_PERSON_SOURCE_IDS
            if "菲" in str(entries.get(entry_id, {}).get("translation", ""))
            or "飞" not in str(entries.get(entry_id, {}).get("translation", ""))
        )
        self.assertEqual(missing, [])
        self.assertEqual(stale_fei, [])

    def test_repairer_labels_use_natural_chinese_person_term(self) -> None:
        paths = sorted((PROJECT_ROOT / "corpus/zh/story-dialogue").glob("*.json"))
        paths.append(PROJECT_ROOT / "corpus/zh/battle/srvc-lines.json")
        allowed_compounds = ("流浪的修理屋", "流浪修理屋")
        allowed_bare = {
            "story/026/dialogue/02.01/0134": (
                "“啊，是的。\n　这位是修理屋的$n。”"
            ),
        }
        unexpected: list[str] = []
        preserved: set[str] = set()
        preserved_bare: set[str] = set()

        for path in paths:
            document = json.loads(path.read_text(encoding="utf-8"))
            for entry in document["entries"]:
                translation = entry.get("translation", "")
                if "修理屋" not in translation:
                    continue
                remainder = translation
                for compound in allowed_compounds:
                    if compound in translation:
                        preserved.add(entry["id"])
                    remainder = remainder.replace(compound, "")
                if "修理屋" in remainder:
                    if allowed_bare.get(entry["id"]) == translation:
                        preserved_bare.add(entry["id"])
                    else:
                        unexpected.append(entry["id"])

        self.assertEqual(unexpected, [])
        self.assertEqual(preserved_bare, set(allowed_bare))
        self.assertEqual(
            preserved,
            {
                "story/014/dialogue/02.02/0073",
                "story/017/dialogue/01.06/0005",
                "story/024/dialogue/01.27/0005",
                "story/025/dialogue/02.01/0212",
                "story/026/dialogue/02.01/0121",
                "story/083/dialogue/01.17/0002",
                "story/111/dialogue/02.01/0273",
                "story/149/dialogue/01.35/0026",
                "story/150/dialogue/02.01/0363",
                "story/150/dialogue/02.01/0749",
                "story/150/dialogue/02.01/1142",
                "story/150/dialogue/02.01/1414",
                "story/150/dialogue/02.01/1433",
            },
        )

    def test_bazaar_status_labels_preserve_original_funds_texture(self) -> None:
        config = _load("config/assets/ui-bazaar-atlas-zh.json")
        corpus = _load("corpus/zh/ui-atlas/bazaar-v2.json")
        decisions = {entry["id"]: entry for entry in corpus["entries"]}
        labels = {
            entry["entry_id"]: entry
            for entry in config["additional_localized_labels"]
        }
        self.assertNotIn("ui-atlas/kvm5/funds", decisions)
        self.assertNotIn("ui-atlas/kvm5/funds", labels)
        self.assertEqual(
            (
                decisions["ui-atlas/kvm5/sr-points"]["source_text"],
                decisions["ui-atlas/kvm5/sr-points"]["translation"],
                labels["ui-atlas/kvm5/sr-points"]["mask"],
            ),
            ("ポイント", "点数", {
                "x": 174,
                "y": 42,
                "width": 53,
                "height": 21,
                "replacement_rgba": "00000000",
                "preserve_rgba": ["00000000"],
            }),
        )
        snapshot = _load(
            "config/assets/ui-bazaar-atlas-render-snapshot.json"
        )
        frozen = {
            entry["entry_id"]: entry for entry in snapshot["labels"]
        }
        self.assertNotIn("ui-atlas/kvm5/funds", frozen)
        points_template = frozen["ui-atlas/kvm5/sr-points"][
            "template_provenance"
        ]
        self.assertEqual(
            points_template["glyphs"],
            [
                {"character": "点", "glyph_index": 3487},
                {"character": "数", "glyph_index": 2964},
            ],
        )
        self.assertEqual(
            points_template["placement"],
            {
                "mask_width": 53,
                "mask_height": 21,
                "cell_width": 20,
                "cell_height": 20,
                "left_offsets": [6, 27],
                "top_offset": 0,
            },
        )
        self.assertEqual(
            sum(
                count
                for index, count in points_template[
                    "logical_index_counts"
                ].items()
                if 8 <= int(index) <= 15
            ),
            243,
        )
        self.assertTrue(points_template["source_palette_histogram_exact"])

    def test_every_component_member_has_one_build_group(self) -> None:
        members = [
            member
            for group in COMPONENT_BUILD_GROUPS
            for member in group["members"]
        ]
        self.assertEqual(len(members), len(set(members)))
        self.assertEqual(set(members), set(ALL_COMPONENT_MEMBERS))
        self.assertEqual(
            [group["id"] for group in COMPONENT_BUILD_GROUPS],
            [
                "core_runtime_members",
                "localized_data_members",
                "rendered_archive_members",
            ],
        )

    def test_release_menu_selection_is_source_bound_and_unique(self) -> None:
        corpus = _load("corpus/zh/menu/release-v0.3.json")
        entries = corpus["entries"]
        expected = corpus["expected"]
        self.assertEqual(corpus["release_id"], "v0.3.0")
        self.assertEqual(
            corpus["selection_authority"],
            "manual_v0.3.0_release_selection",
        )
        self.assertFalse(corpus["release_evidence"]["build_dependency"])
        self.assertEqual(len(entries), expected["entry_count"])
        self.assertEqual(len({entry["id"] for entry in entries}), len(entries))
        entry_by_id = {entry["id"]: entry for entry in entries}
        self.assertEqual(
            entry_by_id["menu/SLPS/00/0343"]["translation"],
            "%s%s",
        )
        self.assertEqual(
            entry_by_id["menu/SLPS/00/0343"]["target_count"],
            2,
        )
        self.assertTrue(
            all(
                len(entry["source_text_sha256"]) == 64
                and entry["target_count"] > 0
                for entry in entries
            )
        )
        member_counts = {
            member: sum(entry["member"] == member for entry in entries)
            for member in ("SLPS", "Compdata")
        }
        self.assertEqual(member_counts, expected["member_entry_counts"])
        raw_ascii_entries = [
            entry for entry in entries if "raw_ascii_characters" in entry
        ]
        self.assertEqual(
            len(raw_ascii_entries),
            expected["raw_ascii_compatible_entry_count"],
        )
        self.assertEqual(raw_ascii_entries[0]["raw_ascii_characters"], "Yo")

    def test_release_menu_codebook_is_one_to_one(self) -> None:
        codebook = _load("config/encoding/release-menu-codebook.json")
        assignments = codebook["assignments"]
        self.assertEqual(codebook["codebook_id"], "srwz-release-menu-v0.3")
        self.assertEqual(len(assignments), codebook["assignment_count"])
        self.assertEqual(
            len({item["character"] for item in assignments}),
            len(assignments),
        )
        self.assertEqual(
            len({item["code"] for item in assignments}),
            len(assignments),
        )
        self.assertEqual(
            len({item["glyph_index"] for item in assignments}),
            len(assignments),
        )
        self.assertEqual(_mapping_sha256(assignments), codebook["mapping_sha256"])

    def test_title_menu_contract_and_eight_slots_are_deterministic(self) -> None:
        contract = _load("config/assets/title-menu-zh.json")
        self.assertEqual(contract["status"], "reviewed_locked")
        self.assertEqual(
            [label["translation"] for label in contract["labels"]],
            ["开始", "读取", "继续", "资料库"],
        )
        masks = []
        for frozen in contract["masks"]:
            mask = zlib.decompress(base64.b64decode(frozen["zlib_base64"]))
            self.assertEqual(len(mask), frozen["size"])
            self.assertEqual(hashlib.sha256(mask).hexdigest(), frozen["sha256"])
            masks.append(mask)

        original = bytes(TITLE_TEXTURE_WIDTH * TITLE_TEXTURE_HEIGHT)
        output, slots = apply_title_menu_masks(original, masks)
        self.assertEqual(len(output), len(original))
        self.assertEqual(len(slots), 8)
        self.assertEqual(
            [slot["y"] for slot in slots],
            [index * TITLE_LABEL_HEIGHT for index in range(8)],
        )
        for slot in slots:
            ramp_base = (
                SELECTED_RAMP_BASE
                if slot["state"] == "selected"
                else UNSELECTED_RAMP_BASE
            )
            start = slot["y"] * TITLE_TEXTURE_WIDTH
            rows = b"".join(
                output[
                    start
                    + row * TITLE_TEXTURE_WIDTH : start
                    + row * TITLE_TEXTURE_WIDTH
                    + TITLE_LABEL_WIDTH
                ]
                for row in range(TITLE_LABEL_HEIGHT)
            )
            self.assertTrue(
                all(ramp_base <= value < ramp_base + RAMP_LEVEL_COUNT for value in rows)
            )


if __name__ == "__main__":
    unittest.main()
