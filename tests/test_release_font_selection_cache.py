"""The translation-tree selection is cached by content beside the identity store."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from srwz import file_identity, release_font


class SelectionCacheTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        (self.root / "corpus/zh/a").mkdir(parents=True)
        self.write("corpus/zh/a/one.json", {"entries": [{"translation": "甲乙", "source_text_sha256": "x"}]})
        self.write("corpus/zh/a/two.json", {"entries": [{"translation": "丙", "editorial_status": "ok"}]})
        store = self.root / "cache/file-identity.json"
        env = patch.dict(os.environ, {file_identity.ENV_STORE: str(store)}); env.start(); self.addCleanup(env.stop)
        os.environ.pop(file_identity.ENV_REHASH, None)  # another test may have set it process-wide
        file_identity.forget_all(); self.addCleanup(file_identity.forget_all)
        self.profile = {"translation_tree_selection": {"root": "corpus/zh", "glob": "**/*.json",
                                                       "field": "translation", "selection_id": "test"}}

    def write(self, relative, document):
        path = self.root / relative
        path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        old = time.time() - 10
        os.utime(path, (old, old))

    def test_second_call_reads_the_pickle_and_edits_invalidate(self):
        first = release_font.selected_translation_tree_entries(self.root, self.profile)
        pickles = list((self.root / "cache/translation-tree-selection").glob("*.pickle"))
        self.assertEqual(len(pickles), 1)
        with patch.object(release_font, "control_notation_tokens", side_effect=AssertionError("walked again")):
            second = release_font.selected_translation_tree_entries(self.root, self.profile)
        self.assertEqual(first, second)
        self.assertEqual(sorted(e["translation"] for e in first[0].values()), ["丙", "甲乙"])
        self.write("corpus/zh/a/two.json", {"entries": [{"translation": "丁"}]})
        third = release_font.selected_translation_tree_entries(self.root, self.profile)
        self.assertEqual(sorted(e["translation"] for e in third[0].values()), ["丁", "甲乙"])
        self.assertEqual(len(list((self.root / "cache/translation-tree-selection").glob("*.pickle"))), 2)


if __name__ == "__main__":
    unittest.main()
