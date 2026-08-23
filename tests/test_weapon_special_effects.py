import copy
import json
import unittest
from pathlib import Path

from tools.srwz.text import (
    load_text_table,
    original_fullwidth_ascii_overrides,
)
from tools.srwz.weapon_special_effects import (
    WeaponSpecialEffectError,
    apply_weapon_special_effect_2,
)


ROOT = Path(__file__).resolve().parents[1]


class WeaponSpecialEffectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(
            (ROOT / "config/full-story-components.json").read_text(
                encoding="utf-8"
            )
        )["weapon_special_effect_2"]
        cls.corpus = json.loads(
            (ROOT / cls.config["corpus"]["path"]).read_text(encoding="utf-8")
        )
        cls.source = (ROOT / "work/disc/SLPS_258.87").read_bytes()
        cls.table = load_text_table(
            ROOT / "vendor/upstream-python/project/tbl_all.json"
        )
        proposal = json.loads(
            (ROOT / "work/writeback/zh-release-codebook-proposal.json").read_text(
                encoding="utf-8"
            )
        )
        primary = {
            row["character"]: int(row["code"], 16)
            for row in proposal["assignments"]
        }
        aliases = {
            row["character"]: int(row["code"], 16)
            for row in proposal["surface_alias_assignments"]
        }
        cls.overrides = {
            **primary,
            **aliases,
            **original_fullwidth_ascii_overrides(cls.table),
        }

    def test_inventory_is_exhaustive_and_translated(self):
        output, report = apply_weapon_special_effect_2(
            self.source,
            self.config,
            self.corpus,
            source_table=self.table,
            encoding_overrides=self.overrides,
        )
        self.assertEqual(report["entry_count"], 2)
        self.assertEqual(
            [row["source"] for row in report["entries"]],
            ["サイズ補正無視", "バリア貫通"],
        )
        self.assertEqual(
            [row["translation"] for row in report["entries"]],
            ["无视体型修正", "屏障贯通"],
        )
        self.assertTrue(report["all_translated_reread_exact"])
        self.assertTrue(report["control_flow_preserved"])
        self.assertEqual(len(output), len(self.source))
        self.assertGreater(report["changed_byte_count"], 0)

    def test_patch_is_idempotent(self):
        output, _report = apply_weapon_special_effect_2(
            self.source,
            self.config,
            self.corpus,
            source_table=self.table,
            encoding_overrides=self.overrides,
        )
        repeated, report = apply_weapon_special_effect_2(
            output,
            self.config,
            self.corpus,
            source_table=self.table,
            encoding_overrides=self.overrides,
        )
        self.assertEqual(repeated, output)
        self.assertEqual(report["changed_byte_count"], 0)
        self.assertTrue(all(row["already_patched"] for row in report["entries"]))

    def test_mixed_instruction_preimage_is_rejected(self):
        broken = bytearray(self.source)
        broken[0x2925A4] ^= 1
        with self.assertRaisesRegex(
            WeaponSpecialEffectError, "instruction preimage drift"
        ):
            apply_weapon_special_effect_2(
                bytes(broken),
                self.config,
                self.corpus,
                source_table=self.table,
                encoding_overrides=self.overrides,
            )

    def test_inventory_ratchet_rejects_a_missing_field(self):
        contract = copy.deepcopy(self.config)
        contract["fields"].pop()
        with self.assertRaisesRegex(WeaponSpecialEffectError, "entry count drift"):
            apply_weapon_special_effect_2(
                self.source,
                contract,
                self.corpus,
                source_table=self.table,
                encoding_overrides=self.overrides,
            )


if __name__ == "__main__":
    unittest.main()
