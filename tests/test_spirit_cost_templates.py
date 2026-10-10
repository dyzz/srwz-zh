import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from srwz.spirit_cost_templates import (
    CAPACITY, EDITIONS, POLICY, SLOTS,
    apply_spirit_cost_templates, verify_spirit_cost_templates,
)


class SpiritCostTemplateTests(unittest.TestCase):
    def fixture(self, edition):
        data = bytearray(b"\xcc" * 0x3C0BE0)
        for ident, _text, offsets in SLOTS:
            payload = bytes.fromhex("8FE8") + bytes.fromhex(
                "8FD9" if ident == "unknown-cost" else "8140") * 3 + bytes.fromhex("8FEB")
            at = offsets[EDITIONS.index(edition)]
            data[at:at + CAPACITY] = payload + bytes(CAPACITY - len(payload))
        # Same text in the separate spirit-command menu is never rewritten.
        other = (0x3449B0, 0x3451A0, 0x3BFF90)[EDITIONS.index(edition)]
        data[other:other + 11] = bytes.fromhex("8FE88FD98FD98FD98FEB00")
        return bytes(data)

    def test_exactly_two_status_templates_change_and_repeat_is_noop(self):
        for edition in EDITIONS:
            with self.subTest(edition=edition):
                before = self.fixture(edition)
                after, report = apply_spirit_cost_templates(before, edition, policy=POLICY)
                changed = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
                self.assertEqual(len(after), len(before))
                self.assertEqual(len(changed), 14)
                self.assertEqual(report["changed_offsets"], [hex(i) for i in changed])
                # Restore only the two authorized allocations; everything
                # else, including identical menu strings, must be exact.
                restored = bytearray(after)
                for _ident, _text, offsets in SLOTS:
                    at = offsets[EDITIONS.index(edition)]
                    restored[at:at + CAPACITY] = before[at:at + CAPACITY]
                self.assertEqual(bytes(restored), before)
                self.assertEqual(verify_spirit_cost_templates(after, edition)["template_count"], 2)
                again, proof = apply_spirit_cost_templates(after, edition)
                self.assertEqual(again, after)
                self.assertEqual(proof["changed_byte_count"], 0)

    def test_exact_native_source_payloads_and_terminators(self):
        output, _ = apply_spirit_cost_templates(self.fixture("original"))
        for _ident, text, offsets in SLOTS:
            native = ("（" + text + "）").encode("cp932")
            self.assertEqual(output[offsets[0]:offsets[0] + CAPACITY],
                             native + bytes(CAPACITY - len(native)))

    def test_rejects_drift_mixed_codes_and_bad_policy(self):
        before = self.fixture("original")
        with self.assertRaisesRegex(ValueError, "not native"):
            verify_spirit_cost_templates(before)
        for offset, value in ((0, 0x81), (2, 0x81), (10, 1), (15, 1)):
            broken = bytearray(before)
            broken[SLOTS[0][2][0] + offset] = value
            with self.assertRaisesRegex(ValueError, "allocation drift"):
                apply_spirit_cost_templates(bytes(broken))
        with self.assertRaisesRegex(ValueError, "outside"):
            apply_spirit_cost_templates(before[:100])
        with self.assertRaisesRegex(ValueError, "unsupported"):
            apply_spirit_cost_templates(before, "other")
        with self.assertRaisesRegex(ValueError, "policy drift"):
            apply_spirit_cost_templates(before, policy={})

    def test_best_offsets_follow_native_piecewise_map(self):
        spans = json.loads((ROOT / "config/editions/best/source-layout.json").read_text())["elf_spans"]
        for _ident, _text, (original, best, _sp) in SLOTS:
            span = next(s for s in spans if s[0] <= original and original + CAPACITY <= s[1])
            self.assertEqual(best, span[2] + original - span[0])

    def test_new_policy_invalidates_existing_component_cache(self):
        from build_full_story_components import _plan_incremental_members
        members, reasons = _plan_incremental_members(
            baseline_config={}, current_config={"spirit_cost_templates": POLICY},
            baseline_remaining_ui={}, current_remaining_ui={}, prior_report={"inputs": {}},
        )
        self.assertIn("SLPS_258.87", members)
        self.assertIn("config:spirit_cost_templates", reasons)
        members, _ = _plan_incremental_members(
            baseline_config={"spirit_cost_templates": POLICY},
            current_config={"spirit_cost_templates": POLICY},
            baseline_remaining_ui={}, current_remaining_ui={}, prior_report={"inputs": {}},
        )
        self.assertEqual(members, set())


if __name__ == "__main__":
    unittest.main()
