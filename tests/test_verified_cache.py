import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from srwz.verified_cache import (
    collect_locked_paths,
    collect_tree_paths,
    validate_verified_cache,
    write_verified_cache,
)


class VerifiedCacheTests(unittest.TestCase):
    def test_exact_file_set_hits_and_content_change_misses(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "config.json"
            second = root / "output.bin"
            cache = root / "work/cache.json"
            first.write_text('{"value": 1}\n', encoding="utf-8")
            second.write_bytes(b"validated-output")
            paths = {first, second}

            receipt = write_verified_cache(
                project_root=root,
                cache_path=cache,
                kind="test-cache",
                paths=paths,
                metadata={"mode": "test"},
            )
            self.assertEqual(receipt["file_count"], 2)
            hit = validate_verified_cache(
                project_root=root,
                cache_path=cache,
                kind="test-cache",
                paths=paths,
                metadata={"mode": "test"},
            )
            self.assertTrue(hit.hit)
            self.assertEqual(hit.checked_file_count, 2)

            second.write_bytes(b"changed-output!!")
            miss = validate_verified_cache(
                project_root=root,
                cache_path=cache,
                kind="test-cache",
                paths=paths,
                metadata={"mode": "test"},
            )
            self.assertFalse(miss.hit)
            self.assertIn("content changed", miss.reason)

    def test_inventory_addition_invalidates_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.txt"
            added = root / "added.txt"
            cache = root / "cache.json"
            source.write_text("source", encoding="utf-8")
            write_verified_cache(
                project_root=root,
                cache_path=cache,
                kind="test-cache",
                paths={source},
            )
            added.write_text("new dependency", encoding="utf-8")
            miss = validate_verified_cache(
                project_root=root,
                cache_path=cache,
                kind="test-cache",
                paths={source, added},
            )
            self.assertFalse(miss.hit)
            self.assertIn("inventory changed", miss.reason)

    def test_collectors_include_tree_and_nested_locks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            definitions = root / "config"
            definitions.mkdir()
            config = definitions / "build.json"
            payload = root / "work/output.bin"
            payload.parent.mkdir()
            config.write_text("{}\n", encoding="utf-8")
            (definitions / ".DS_Store").write_bytes(b"local metadata")
            payload.write_bytes(b"payload")
            document = {
                "nested": {
                    "path": "work/output.bin",
                    "size": len(b"payload"),
                    "sha256": "0" * 64,
                }
            }

            self.assertEqual(
                collect_tree_paths(root, ["config"]),
                {config.resolve()},
            )
            self.assertEqual(
                collect_locked_paths(root, document),
                {payload.resolve()},
            )

    def test_cache_path_cannot_escape_project(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.txt"
            source.write_text("source", encoding="utf-8")
            with self.assertRaises(ValueError):
                write_verified_cache(
                    project_root=root,
                    cache_path=root.parent / "outside-cache.json",
                    kind="test-cache",
                    paths={source},
                )


if __name__ == "__main__":
    unittest.main()
