import copy
import json
import re
import unittest
from pathlib import Path

from tools.srwz.display_names import (
    DisplayNameError,
    build_display_name_report,
    load_display_name_source,
    parse_display_names,
)
from tools.srwz.text import load_text_table


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config/display-names/compdata.json"
MANIFEST_PATH = PROJECT_ROOT / "manifests/display-name-structure.json"


class DisplayNameParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        (
            _,
            cls.decoded,
            cls.parsed,
            _,
        ) = load_display_name_source(PROJECT_ROOT, CONFIG_PATH)
        cls.table = load_text_table(PROJECT_ROOT / cls.config["text_table"]["path"])

    def test_complete_pilot_and_unit_structures(self):
        self.assertEqual(len(self.parsed.pilot_entries), 2799)
        self.assertEqual(len(self.parsed.unit_entries), 348)
        self.assertEqual(
            sum(bool(entry.text) for entry in self.parsed.pilot_entries),
            2452,
        )
        self.assertEqual(
            sum(len(entry.pointer_offsets) for entry in self.parsed.unit_entries),
            808,
        )
        self.assertEqual(
            len({entry.entry_id for entry in self.parsed.entries}),
            3147,
        )

    def test_known_probes_have_stable_ids_and_allocations(self):
        entries = {entry.entry_id: entry for entry in self.parsed.entries}
        setsuko = entries["display-name/pilot/0702/display"]
        denzel = entries["display-name/pilot/0708/display"]
        vargora = entries["display-name/unit/0316/name"]
        self.assertEqual((setsuko.target_offset, setsuko.capacity), (0x20402, 21))
        self.assertEqual((denzel.target_offset, denzel.capacity), (0x20822, 21))
        self.assertEqual((vargora.target_offset, vargora.capacity), (0x6E9F0, 24))
        self.assertEqual(vargora.pointer_record_indices, (732, 733, 739, 740))

    def test_manifest_is_bounded_and_reproducible(self):
        _, manifest = build_display_name_report(PROJECT_ROOT, CONFIG_PATH)
        committed = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        self.assertEqual(manifest, committed)
        serialized = json.dumps(manifest, ensure_ascii=False)
        self.assertIsNone(
            re.search(r"[\u3041-\u3096\u30a1-\u30fa\u30fd-\u30ff]", serialized)
        )
        self.assertEqual(manifest["runtime"]["status"], "not_tested")

    def test_parser_rejects_record_count_drift(self):
        changed = copy.deepcopy(self.config)
        changed["pilot_table"]["record_count"] = 932
        with self.assertRaisesRegex(
            DisplayNameError,
            "pilot table extent is inconsistent",
        ):
            parse_display_names(self.decoded, self.table, changed)

    def test_parser_rejects_nonzero_pilot_padding(self):
        changed = bytearray(self.decoded)
        entry = next(
            item
            for item in self.parsed.pilot_entries
            if item.entry_id == "display-name/pilot/0702/display"
        )
        changed[entry.target_offset + entry.encoded_size] = 0x41
        changed_config = copy.deepcopy(self.config)
        start = int(changed_config["pilot_table"]["start"], 0)
        end = int(changed_config["pilot_table"]["end"], 0)
        import hashlib

        changed_config["pilot_table"]["table_sha256"] = hashlib.sha256(
            changed[start:end]
        ).hexdigest()
        with self.assertRaisesRegex(DisplayNameError, "nonzero field padding"):
            parse_display_names(bytes(changed), self.table, changed_config)


if __name__ == "__main__":
    unittest.main()
