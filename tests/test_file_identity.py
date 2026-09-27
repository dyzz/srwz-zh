"""One SHA-256 per file identity; clones inherit, edits and rewrites re-hash."""
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from srwz import file_identity
from srwz.release_inputs import copy_file


class FileIdentityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.store = self.root / "cache/file-identity.json"
        env = patch.dict(os.environ, {file_identity.ENV_STORE: str(self.store)}, clear=False)
        env.start();self.addCleanup(env.stop)
        os.environ.pop(file_identity.ENV_REHASH, None)
        file_identity.forget_all();self.addCleanup(file_identity.forget_all)

    def aged(self, path, data):
        path.write_bytes(data)
        old = time.time() - 10
        os.utime(path, (old, old))
        return path

    def test_digest_matches_hashlib_and_is_computed_once_per_identity(self):
        path = self.aged(self.root / "big.bin", bytes(range(256)) * 8192)
        expected = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(file_identity.sha256_file(path), expected)
        with patch.object(file_identity, "_hash_range", side_effect=AssertionError("re-hashed")):
            self.assertEqual(file_identity.sha256_file(path), expected)
            self.assertEqual(file_identity.sha256_range(path, 0, path.stat().st_size), expected)
        self.assertTrue(self.store.is_file())

    def test_rewrite_and_in_place_edit_invalidate(self):
        path = self.aged(self.root / "big.bin", b"a" * (2 * 1024 * 1024))
        first = file_identity.sha256_file(path)
        with path.open("r+b") as stream:
            stream.seek(0);stream.write(b"b")
        self.assertNotEqual(file_identity.sha256_file(path), first)
        self.aged(path, b"c" * (2 * 1024 * 1024))
        self.assertEqual(file_identity.sha256_file(path), hashlib.sha256(path.read_bytes()).hexdigest())

    def test_fresh_files_are_not_persisted_until_stable(self):
        path = self.root / "fresh.bin";path.write_bytes(b"x" * (2 * 1024 * 1024))
        file_identity.sha256_file(path)
        self.assertFalse(self.store.exists())

    def test_store_is_shared_across_processes_and_disabled_by_rehash(self):
        path = self.aged(self.root / "big.bin", bytes(range(256)) * 8192)
        digest = file_identity.sha256_file(path)
        file_identity.forget_all()
        with patch.object(file_identity, "_hash_range", side_effect=AssertionError("re-hashed")):
            self.assertEqual(file_identity.sha256_file(path), digest)
        file_identity.forget_all()
        with patch.dict(os.environ, {file_identity.ENV_REHASH: "1"}):
            with patch.object(file_identity, "_hash_range", return_value=digest) as hashed:
                self.assertEqual(file_identity.sha256_file(path), digest)
                hashed.assert_called_once()

    def test_range_digests_bind_to_offset_and_identity(self):
        path = self.aged(self.root / "disc.bin", bytes(range(256)) * 8192)
        data = path.read_bytes()
        self.assertEqual(file_identity.sha256_range(path, 2048, 4096), hashlib.sha256(data[2048:6144]).hexdigest())
        self.assertNotEqual(file_identity.sha256_range(path, 0, 4096), file_identity.sha256_range(path, 100, 4096))
        with self.assertRaises(OSError):
            file_identity.sha256_range(path, len(data) - 10, 4096)

    @unittest.skipUnless(sys.platform == "darwin", "APFS clone semantics")
    def test_clone_inherits_verified_digest_and_diverges_after_write(self):
        path = self.aged(self.root / "big.bin", bytes(range(256)) * 8192)
        digest = file_identity.sha256_file(path)
        clone = self.root / "clone.bin"
        copy_file(path, clone)
        self.assertNotEqual(clone.stat().st_ino, path.stat().st_ino)
        with patch.object(file_identity, "_hash_range", side_effect=AssertionError("re-hashed")):
            self.assertEqual(file_identity.sha256_file(clone), digest)
        with clone.open("r+b") as stream:
            stream.write(b"z")
        self.assertNotEqual(file_identity.sha256_file(clone), digest)
        self.assertEqual(file_identity.sha256_file(path), digest)

    def test_range_only_record_does_not_answer_a_whole_file_request(self):
        path = self.aged(self.root / "disc.bin", bytes(range(256)) * 8192)
        file_identity.sha256_range(path, 2048, 4096)
        self.assertEqual(file_identity.sha256_file(path), hashlib.sha256(path.read_bytes()).hexdigest())

    def test_range_only_record_survives_store_reload(self):
        path = self.aged(self.root / "disc.bin", bytes(range(256)) * 8192)
        digest = file_identity.sha256_range(path, 2048, 4096)
        file_identity.forget_all()
        with patch.object(file_identity, "_hash_range", side_effect=AssertionError("re-hashed range")):
            self.assertEqual(file_identity.sha256_range(path, 2048, 4096), digest)
        self.assertEqual(file_identity.sha256_file(path), hashlib.sha256(path.read_bytes()).hexdigest())

    def test_unknown_source_clone_is_simply_hashed(self):
        path = self.aged(self.root / "big.bin", b"q" * (2 * 1024 * 1024))
        clone = self.root / "clone.bin"
        self.assertFalse(file_identity.record_clone(path, self.aged(clone, path.read_bytes())))
        self.assertEqual(file_identity.sha256_file(clone), hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
