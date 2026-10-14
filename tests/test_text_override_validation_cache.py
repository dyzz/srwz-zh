"""The override table is validated once per table object, not once per record."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from srwz import text


class OverrideValidationCacheTests(unittest.TestCase):
    def test_same_table_object_reuses_the_validated_view(self):
        table = {"Ａ": 0x8260, "Ｂ": 0x8261}
        first = text._validated_overrides(table)
        self.assertIs(text._validated_overrides(table), first)
        self.assertEqual(dict(first), table)
        table["Ｃ"] = 0x8262
        self.assertEqual(dict(text._validated_overrides(table)), table)
        with self.assertRaises(ValueError):
            text._validated_overrides({"AB": 1})
        self.assertEqual(dict(text._validated_overrides({})), {})


if __name__ == "__main__":
    unittest.main()
