import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from srwz.weapon_detail_parentheses import (
    EDITIONS, SLOTS, apply_weapon_detail_parentheses, verify_weapon_detail_parentheses,
)


class WeaponDetailParenthesesTests(unittest.TestCase):
    def fixture(self, edition):
        index = EDITIONS.index(edition)
        data = bytearray(b"\xcc" * 0x3C0D20)
        for ident, spaces, capacity, offsets in SLOTS:
            at = offsets[index]
            prefix = b"\x82\x6f" if ident in ("map", "tri", "all", "pla") else b""
            payload = prefix + b"\x8f\xe8" + b"\x81\x40" * spaces + b"\x8f\xeb\0"
            data[at:at + capacity] = payload + bytes(capacity - len(payload))
        # Identical punctuation elsewhere must retain the current alias policy.
        data[100:106] = bytes.fromhex("8fe881408feb")
        return bytes(data)

    def test_only_seven_templates_change_in_each_edition(self):
        for edition in EDITIONS:
            with self.subTest(edition=edition):
                before = self.fixture(edition)
                after, report = apply_weapon_detail_parentheses(before, edition)
                changed = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
                self.assertEqual(len(before), len(after))
                self.assertEqual(len(changed), 28)
                self.assertEqual([hex(i) for i in changed], report["changed_offsets"])
                self.assertEqual(after[100:106], before[100:106])
                again, repeat = apply_weapon_detail_parentheses(after, edition)
                self.assertEqual(again, after)
                self.assertEqual(repeat["changed_byte_count"], 0)
                self.assertEqual(verify_weapon_detail_parentheses(after, edition)["template_count"], 7)

    def test_rejects_bad_slots_and_non_native_readback(self):
        before = self.fixture("sp")
        with self.assertRaisesRegex(ValueError, "not native"):
            verify_weapon_detail_parentheses(before, "sp")
        with self.assertRaisesRegex(ValueError, "outside"):
            apply_weapon_detail_parentheses(before[:100], "sp")
        with self.assertRaisesRegex(ValueError, "unsupported"):
            apply_weapon_detail_parentheses(before, "unknown")
        for replacement in (b"\x81\x69", b"\x20\x20", b"\x81\x41"):
            broken = bytearray(before)
            # Mixed code classes, raw ASCII spaces, or changed placeholders
            # cannot silently authorize a wider search/replacement.
            at = 0x3C0CF0 if replacement == b"\x81\x69" else 0x3C0CF2
            broken[at:at + 2] = replacement
            with self.assertRaisesRegex(ValueError, "suffix drift"):
                apply_weapon_detail_parentheses(bytes(broken), "sp")

    def test_best_locations_follow_audited_piecewise_map(self):
        spans = json.loads((ROOT / "config/editions/best/source-layout.json").read_text())["elf_spans"]
        for _ident, _spaces, capacity, (original, best, _sp) in SLOTS:
            span = next(s for s in spans if s[0] <= original and original + capacity <= s[1])
            self.assertEqual(best, span[2] + original - span[0])

    def test_new_policy_invalidates_old_component_cache(self):
        from build_full_story_components import _plan_incremental_members
        from srwz.weapon_detail_parentheses import POLICY
        members, reasons = _plan_incremental_members(
            baseline_config={}, current_config={"weapon_detail_parentheses": POLICY},
            baseline_remaining_ui={}, current_remaining_ui={}, prior_report={"inputs": {}},
        )
        self.assertIn("SLPS_258.87", members)
        self.assertIn("config:weapon_detail_parentheses", reasons)
        unchanged, _ = _plan_incremental_members(
            baseline_config={"weapon_detail_parentheses": POLICY},
            current_config={"weapon_detail_parentheses": POLICY},
            baseline_remaining_ui={}, current_remaining_ui={}, prior_report={"inputs": {}},
        )
        self.assertEqual(unchanged, set())


if __name__ == "__main__":
    unittest.main()
