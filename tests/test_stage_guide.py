import hashlib
import json
import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GUIDE = PROJECT_ROOT / "guide/srwz-z-flow-guide.html"
MANIFEST = PROJECT_ROOT / "guide/stage-guide-manifest.json"
HIDDEN = PROJECT_ROOT / "guide/data/hidden-elements.json"
PROGRESSION = PROJECT_ROOT / "guide/data/progression.json"
REFERENCE = PROJECT_ROOT / "guide/data/reference.json"


class StageGuideTests(unittest.TestCase):
    def test_stage_guide_coverage_and_evidence_contract(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        coverage = manifest["coverage"]
        self.assertEqual(coverage["playable_title_count"], 107)
        self.assertEqual(coverage["playable_resource_number_count"], 107)
        self.assertEqual(coverage["playable_chunk_count"], 153)
        self.assertEqual(coverage["flow_condition_count"], 658)
        self.assertEqual(coverage["all_parsed_condition_count"], 670)
        self.assertEqual(coverage["condition_corpus_count"], 670)
        self.assertEqual(coverage["hidden_entry_count"], 36)
        self.assertEqual(coverage["hidden_step_count"], 160)
        self.assertEqual(coverage["progression_entry_count"], 135)
        self.assertEqual(coverage["progression_stage_card_count"], 101)
        self.assertEqual(coverage["akurasu_correction_count"], 1)
        self.assertEqual(coverage["akurasu_hidden_text_correction_count"], 7)
        self.assertEqual(coverage["akurasu_correction_card_count"], 1)
        self.assertEqual(coverage["reference_upgrade_carryover_count"], 20)
        self.assertEqual(coverage["reference_full_upgrade_bonus_count"], 14)
        self.assertEqual(coverage["reference_pilot_skill_count"], 45)
        self.assertEqual(coverage["reference_pilot_skill_level_table_count"], 15)
        self.assertEqual(coverage["reference_rare_pilot_skill_count"], 12)
        self.assertEqual(coverage["reference_leadership_category_count"], 15)
        self.assertEqual(coverage["reference_leadership_effect_count"], 59)
        self.assertEqual(coverage["reference_rare_leadership_effect_count"], 19)
        self.assertEqual(coverage["reference_mech_ability_count"], 45)
        self.assertEqual(coverage["reference_bazaar_part_count"], 28)
        self.assertEqual(coverage["reference_bazaar_unit_count"], 15)
        self.assertEqual(coverage["reference_team_attack_count"], 12)
        verified = coverage["progression_verification_counts"]
        self.assertGreater(
            verified["stage-script"] + verified["stage-script-partial"],
            verified["guide-supplement"],
        )
        self.assertEqual(sum(coverage["evidence_level_counts"].values()), 160)
        self.assertGreaterEqual(coverage["used_global_term_count"], 200)

    def test_every_playable_resource_has_a_locked_stage_witness(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(
            set(manifest["resources"]),
            {f"{number:03d}" for number in range(1, 108)},
        )
        for number, chunks in manifest["resources"].items():
            self.assertTrue(chunks)
            for chunk in chunks:
                self.assertRegex(chunk["resource_name"], rf"^stg_{number}[a-z]?\.bin$")
                self.assertRegex(chunk["function_address"], r"^0x[0-9A-F]{8}$")
                self.assertRegex(chunk["stored_sha256"], r"^[0-9a-f]{64}$")
                self.assertRegex(chunk["decoded_sha256"], r"^[0-9a-f]{64}$")

    def test_guide_entries_are_rendered_and_globally_term_bound(self):
        source = json.loads(HIDDEN.read_text(encoding="utf-8"))
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        page = GUIDE.read_text(encoding="utf-8")
        ids = [entry["id"] for entry in source["entries"]]
        self.assertEqual(len(ids), 36)
        self.assertEqual(len(set(ids)), 36)
        for entry_id in ids:
            self.assertIn(f'id="secret-{entry_id}"', page)
        placeholders = set()
        for source_path in (HIDDEN, PROGRESSION, REFERENCE):
            placeholders.update(
                re.findall(
                    r"\{\{([^{}]+)\}\}",
                    source_path.read_text(encoding="utf-8"),
                )
            )
        self.assertEqual(placeholders, set(manifest["terminology"]["used_ids"]))
        self.assertEqual(set(manifest["terminology"]["sources"]), placeholders)

    def test_player_names_units_and_weapons_use_global_term_ids(self):
        page = GUIDE.read_text(encoding="utf-8")
        progression = PROGRESSION.read_text(encoding="utf-8")
        hidden = HIDDEN.read_text(encoding="utf-8")
        reference = REFERENCE.read_text(encoding="utf-8")

        for term_ref in (
            "{{people/leben}}",
            "{{unit/chaos-leo}}",
            "{{people/anemone}}",
            "{{people/sara-tyrell}}",
            "{{unit/brockary}}",
            "{{unit/baldios}}",
            "{{weapon/0235}}",
        ):
            with self.subTest(term_ref=term_ref):
                self.assertIn(term_ref, progression + hidden + reference)

        for stale in (
            "勒温",
            "混沌利奥",
            "安妮莫奈",
            "莎拉·泰瑞尔",
            "布拉卡利",
            "巴尔迪奥斯",
        ):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, page)

        self.assertIn("雷本驾驶混沌·雷欧参战", page)
        self.assertIn("阿尼莫奈", page)
        self.assertIn("莎拉·泰雷尔", page)
        self.assertIn("布洛克利", page)
        self.assertIn("巴鲁迪奥斯", page)
        self.assertIn("百式默认解锁超级米加发射器", page)

    def test_player_ui_has_ten_views_and_no_collapsed_content(self):
        page = GUIDE.read_text(encoding="utf-8")
        self.assertEqual(page.count('<a class="mode-tab'), 10)
        self.assertEqual(page.count('class="guide-panel"'), 10)
        self.assertNotIn("<details", page)
        self.assertNotIn("<summary", page)
        self.assertNotIn('class="hero', page)
        self.assertNotIn('class="toolbar', page)
        self.assertNotIn('type="search"', page)
        self.assertNotIn("证据定位", page)
        self.assertNotIn("全局术语绑定", page)
        self.assertIn("加入／取得", page)
        self.assertIn("临时参战", page)
        self.assertIn("离队／换机", page)
        self.assertIn("强化／新能力", page)
        self.assertIn("本话隐藏进度", page)
        self.assertIn("周目继承", page)
        self.assertIn("剧情换机改造继承", page)
        self.assertIn("通用全改造奖励", page)
        self.assertIn("小队长能力", page)
        self.assertIn("游戏内全部45项特殊技能", page)
        self.assertIn("游戏内有名称的机体特殊能力", page)
        self.assertIn("常规强化零件", page)
        self.assertIn("可购买机体", page)
        self.assertIn("合体攻击一览", page)
        self.assertNotIn("驾驶员数据库", page)
        self.assertIn("Akurasu 资料差异", page)
        self.assertNotIn("胜败／SR条件", page)
        self.assertNotIn('class="conditions-block"', page)
        self.assertNotIn('class="condition-kind"', page)
        self.assertEqual(page.count('class="stage-block correction"'), 1)
        self.assertNotIn("英文拼写混用", page)
        self.assertNotIn("英文武器名拼写", page)
        self.assertNotIn("Gundam XX", page)
        self.assertNotIn("Chaos Caper", page)
        self.assertIn("同一格重复列出", page)

    def test_pilot_skill_effects_and_rare_holders_are_rendered(self):
        page = GUIDE.read_text(encoding="utf-8")
        seed = page.split("<h3>SEED</h3>", 1)[1].split("</article>", 1)[0]
        extended = page.split("<h3>扩展人</h3>", 1)[1].split("</article>", 1)[0]
        commander = page.split("<h3>指挥官</h3>", 1)[1].split("</article>", 1)[0]
        genius = page.split("<h3>天才</h3>", 1)[1].split("</article>", 1)[0]
        extreme = page.split("<h3>极</h3>", 1)[1].split("</article>", 1)[0]
        double_action = page.split("<h3>二次行动</h3>", 1)[1].split(
            "</article>", 1
        )[0]
        self.assertIn("最终伤害变为1.1倍", seed)
        self.assertIn("最终命中率、回避率和暴击率＋20%", seed)
        self.assertNotIn("技能等级", seed)
        self.assertNotIn('class="skill-level-detail"', seed)
        self.assertIn("技能等级越高，效果越强", extended)
        self.assertIn("命中率、回避率和暴击率提高", extended)
        self.assertIn('class="skill-level-detail"', extended)
        self.assertIn("L7", extended)
        self.assertIn("本作没有L8、L9数据", extended)
        self.assertIn("距离5", commander)
        self.assertIn("L4", commander)
        self.assertIn("持有人：真、阿斯兰、基拉、拉克丝", seed)
        self.assertIn("持有人：斯汀、奥尔、史黛拉", extended)
        self.assertIn("持有人：桑德曼（我方常驻）", genius)
        self.assertIn("持有人：金卡拉姆（客串友军；无常驻我方持有者）", extreme)
        self.assertIn("敌方专用", double_action)
        self.assertIn("我方常驻与可控客串角色均无人持有", double_action)
        self.assertIn(
            "持有人：桂、苏茜亚、卡洛德、凯吉南（客串友军）、贝克（客串友军）",
            page,
        )
        self.assertEqual(page.count('class="skill-level-detail"'), 15)
        self.assertEqual(page.count('class="rare-badge"'), 31)
        self.assertIn("持有人：托比", page)
        self.assertIn("持有人：兰德", page)
        self.assertIn("持有人去重后不超过5人的技能标为稀有", page)
        self.assertIn("Akurasu 把指挥官写成最高L9", page)
        self.assertIn("Akurasu 把扩展人概括为最高L9", page)
        self.assertIn("拉克丝的舰长效果", page)
        self.assertIn("漏掉托比效果的“援护时”限定", page)

    def test_single_file_page_has_no_runtime_network_dependency(self):
        page = GUIDE.read_text(encoding="utf-8")
        self.assertTrue(page.startswith("<!doctype html>"))
        self.assertIn('<script type="application/json" id="guide-manifest">', page)
        self.assertIsNone(
            re.search(r"<(?:script|img)[^>]+src=[\"']https?://", page, re.I)
        )
        self.assertIsNone(re.search(r"<link[^>]+href=[\"']https?://", page, re.I))
        self.assertNotIn("@import", page)
        self.assertNotIn("fetch(", page)
        for ordinal in range(107):
            self.assertIn(f'id="stage-{ordinal:03d}"', page)

    def test_manifest_input_hashes_are_current(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        for relative, lock in manifest["inputs"].items():
            payload = (PROJECT_ROOT / relative).read_bytes()
            self.assertEqual(len(payload), lock["size"])
            self.assertEqual(hashlib.sha256(payload).hexdigest(), lock["sha256"])


if __name__ == "__main__":
    unittest.main()
