import hashlib
import json
import unittest
from pathlib import Path

from tools.build_full_story_components import (
    _apply_fixed_span_translations,
    _full_story_overrides,
    _stored_text_overrides,
)
from tools.srwz.codec import decode_production
from tools.srwz.chinese_layout import rendered_line_width
from tools.srwz.release_font_policy import (
    DEFAULT_WIDTH_CLASS,
    allocation_width_class,
)
from tools.srwz.text import (
    decode_text,
    load_text_table,
    original_fullwidth_ascii_overrides,
    project_runtime_text_table,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REMAINING_UI = PROJECT_ROOT / "corpus/zh/menu/remaining-ui.json"
PARTS = PROJECT_ROOT / "corpus/zh/menu/system-ui-parts.json"
SOURCE_SLPS = PROJECT_ROOT / "work/disc/SLPS_258.87"
SOURCE_COMPDATA = PROJECT_ROOT / "work/disc/DATA/COMPDATA.BN"
TEXT_TABLE = PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
FONT_MANIFEST = PROJECT_ROOT / "manifests/zh-release-font-validation.json"
FULL_STORY_CONFIG = PROJECT_ROOT / "config/full-story-components.json"


class PostReleaseStaticFixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.remaining = json.loads(REMAINING_UI.read_text(encoding="utf-8"))
        cls.parts = json.loads(PARTS.read_text(encoding="utf-8"))
        cls.source_slps = SOURCE_SLPS.read_bytes()
        cls.source_compdata = decode_production(
            SOURCE_COMPDATA.read_bytes()
        ).output
        cls.source_table = load_text_table(TEXT_TABLE)
        font_manifest = json.loads(FONT_MANIFEST.read_text(encoding="utf-8"))
        _, primary, aliases, _ = _full_story_overrides(font_manifest)
        cls.primary = primary
        cls.aliases = aliases
        cls.encoding_overrides = _stored_text_overrides(
            cls.source_table,
            primary,
            aliases,
        )
        cls.output_table = project_runtime_text_table(
            cls.source_table,
            primary,
        )
        cls.output_table = project_runtime_text_table(
            cls.output_table,
            aliases,
        )
        cls.output_table = project_runtime_text_table(
            cls.output_table,
            original_fullwidth_ascii_overrides(cls.source_table),
        )

    def test_new_fixed_slps_slots_are_source_locked(self):
        expected_sources = {
            "0x33E3B0": "トリニティチャージ",
            "0x342618": "射程範囲外",
            "0x343AD0": "戦術換装",
            "0x343AE8": "トリニティＣ",
            "0x345ED8": "艦長効果",
        }
        expected_translations = {
            "0x33E3B0": "充能",
            "0x342618": "射程外",
            "0x343AD0": "战术换装",
            "0x343AE8": "充能",
            "0x345ED8": "舰长效果",
        }
        for raw_offset, source_text in expected_sources.items():
            decoded = decode_text(
                self.source_slps,
                int(raw_offset, 16),
                self.source_table,
            )
            self.assertEqual(decoded.text, source_text)
        fixed = self.remaining["slps_by_offset"]
        self.assertEqual(
            {offset: fixed[offset] for offset in expected_translations},
            expected_translations,
        )

    def test_trinity_charge_never_exceeds_original_display_width(self):
        surfaces = (
            (
                self.source_compdata,
                "0x6B5C0",
                self.remaining["compdata_direct_by_offset"]["0x6B5C0"],
                9,
            ),
            (
                self.source_compdata,
                "0x742C0",
                self.remaining["compdata_direct_by_offset"]["0x742C0"],
                9,
            ),
            (
                self.source_slps,
                "0x33E3B0",
                self.remaining["slps_by_offset"]["0x33E3B0"],
                9,
            ),
            (
                self.source_slps,
                "0x343AE8",
                self.remaining["slps_by_offset"]["0x343AE8"],
                6,
            ),
        )
        for source_data, raw_offset, translation, expected_source_width in surfaces:
            source = decode_text(
                source_data,
                int(raw_offset, 16),
                self.source_table,
            )
            source_width = rendered_line_width(source.text)
            translation_width = rendered_line_width(translation)
            self.assertEqual(source_width, expected_source_width)
            self.assertEqual(translation_width, 2)
            self.assertLessEqual(
                translation_width,
                source_width,
                msg=f"{raw_offset} exceeds original display width",
            )

    def test_special_map_commands_use_full_width_primaries_without_padding(self):
        fixed = self.remaining["slps_by_offset"]
        expectations = {
            "0x343AD0": ("戦術換装", "战术换装", 4),
            "0x343AE8": ("トリニティＣ", "充能", 6),
        }
        for raw_offset, (source_text, translation, width) in expectations.items():
            source = decode_text(
                self.source_slps,
                int(raw_offset, 16),
                self.source_table,
            )
            self.assertEqual(source.text, source_text)
            self.assertEqual(fixed[raw_offset], translation)
            self.assertEqual(rendered_line_width(source_text), width)
            self.assertLessEqual(rendered_line_width(translation), width)
            self.assertFalse(translation.startswith((" ", "　")))
            self.assertFalse(translation.endswith((" ", "　")))
            for character in translation:
                code = self.primary.get(character, self.aliases.get(character))
                self.assertIsNotNone(code, msg=f"missing mapping for {character!r}")
                self.assertEqual(
                    allocation_width_class(code),
                    DEFAULT_WIDTH_CLASS,
                    msg=f"special command glyph is not full width: {character!r}",
                )

    def test_issue_008_formation_help_avoids_spaced_all_and_narrow_overflow(self):
        expected = {
            "0x7E490": (
                "TRI攻击可用，小队攻击不可用\n"
                "可援防，队员抗全体攻击能力提升"
            ),
            "0x7E500": (
                "集中攻击单体，队员攻击力50%\n"
                "可援防，共享屏障，队长抗全体攻击"
            ),
            "0x7E590": (
                "分散攻击目标，队员攻击力80%\n"
                "不可援防，队员抗全体攻击能力提升"
            ),
        }
        fixed = self.remaining["compdata_direct_by_offset"]
        self.assertEqual({offset: fixed[offset] for offset in expected}, expected)
        for raw_offset, translation in expected.items():
            for line in translation.splitlines():
                self.assertNotIn("ALL", line)
                self.assertNotIn("　", line)
                self.assertLessEqual(
                    rendered_line_width(line),
                    18,
                    msg=(
                        f"{raw_offset} exceeds the observed narrow help panel: "
                        f"{line!r}"
                    ),
                )

    def test_issue_021_parameter_tab_keeps_one_fullwidth_anchor_space(self):
        fixed = self.remaining["slps_by_offset"]
        self.assertEqual(fixed["0x341160"], "　参数提升")
        self.assertEqual(
            self.remaining["accepted_current_preimages_by_offset"]["0x341160"],
            "参数提升",
        )
        source = decode_text(
            self.source_slps,
            0x341160,
            self.source_table,
        )
        self.assertEqual(source.text, "パラメータ上昇")

    def test_issue_019_gravion_combine_confirmation_is_source_locked(self):
        source = decode_text(
            self.source_compdata,
            0x7E9A0,
            self.source_table,
        )
        self.assertEqual(
            source.text,
            "合神して３ターン経過するとゴッドグラヴィオンは\n"
            "重力子臨界を迎え、合神は自動的に解除されます。\n"
            "その後、同じマップ上では、再合神は出来ません。\n"
            "合神しますか？",
        )
        self.assertEqual(
            self.remaining["compdata_direct_by_offset"]["0x7E9A0"],
            "合神后经过3回合，神机超重神将达到\n"
            "重力子临界，合神会自动解除。\n"
            "之后在本地图内无法再次合神。\n"
            "要合神吗？",
        )

    def test_fixed_slot_writer_accepts_all_post_release_translations(self):
        slps_offsets = (
            "0x33E3B0",
            "0x341160",
            "0x342618",
            "0x343AD0",
            "0x343AE8",
            "0x345ED8",
        )
        slps_replacements = {
            offset: self.remaining["slps_by_offset"][offset]
            for offset in slps_offsets
        }
        output_slps, slps_report = _apply_fixed_span_translations(
            self.source_slps,
            self.source_slps,
            slps_replacements,
            table=self.source_table,
            output_table=self.output_table,
            encoding_overrides=self.encoding_overrides,
            label="post-release SLPS regression",
        )
        self.assertTrue(slps_report["reread_exact"])
        self.assertEqual(slps_report["entry_count"], len(slps_offsets))
        for raw_offset, translation in slps_replacements.items():
            reread = decode_text(
                output_slps,
                int(raw_offset, 16),
                self.output_table,
            )
            self.assertEqual(reread.text, translation)

        compdata_offsets = ("0x7E490", "0x7E500", "0x7E590", "0x7E9A0")
        compdata_replacement = {
            offset: self.remaining["compdata_direct_by_offset"][offset]
            for offset in compdata_offsets
        }
        output_compdata, compdata_report = _apply_fixed_span_translations(
            self.source_compdata,
            self.source_compdata,
            compdata_replacement,
            table=self.source_table,
            output_table=self.output_table,
            encoding_overrides=self.encoding_overrides,
            label="post-release COMPDATA regression",
        )
        self.assertTrue(compdata_report["reread_exact"])
        self.assertEqual(compdata_report["entry_count"], len(compdata_offsets))
        for raw_offset, translation in compdata_replacement.items():
            reread = decode_text(
                output_compdata,
                int(raw_offset, 16),
                self.output_table,
            )
            self.assertEqual(reread.text, translation)

    def test_issue_012_terrain_part_first_lines_fit_reported_panel(self):
        entries = {entry["id"]: entry for entry in self.parts["entries"]}
        expected_first_lines = {
            "menu/Compdata/01/0041": "机体、武器的空中适应变为S",
            "menu/Compdata/01/0045": "机体、武器的陆地适应变为S",
            "menu/Compdata/01/0047": "机体、武器的海中适应变为S",
        }
        for entry_id, expected in expected_first_lines.items():
            first_line = entries[entry_id]["translation"].splitlines()[0]
            self.assertEqual(first_line, expected)
            self.assertLessEqual(len(first_line), 13)

    def test_issue_012_all_part_descriptions_fit_panel_contract(self):
        for entry in self.parts["entries"]:
            lines = entry["translation"].splitlines()
            self.assertLessEqual(
                len(lines),
                3,
                msg=f"{entry['id']} exceeds the three-line panel",
            )
            for line in lines:
                self.assertLessEqual(
                    len(line),
                    13,
                    msg=f"{entry['id']} line exceeds 13 glyph cells: {line!r}",
                )

    def test_all_remaining_ui_dependency_locks_match_the_same_corpus(self):
        payload = REMAINING_UI.read_bytes()
        expected_lock = {
            "path": "corpus/zh/menu/remaining-ui.json",
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        config = json.loads(FULL_STORY_CONFIG.read_text(encoding="utf-8"))
        matched_locks = []

        def collect(value):
            if isinstance(value, dict):
                if value.get("path") == expected_lock["path"]:
                    matched_locks.append(value)
                for child in value.values():
                    collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)

        collect(config)
        self.assertEqual(len(matched_locks), 4)
        self.assertTrue(all(lock == expected_lock for lock in matched_locks))


if __name__ == "__main__":
    unittest.main()
