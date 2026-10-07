"""The shared Rust payload cache must be exact, self-checking and bypassable."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from srwz import codec
from srwz.file_identity import ENV_REHASH


class CompressionCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.binary = root / 'srwz-compress'
        self.binary.write_bytes(b'compressor build A')
        self.cache = root / 'cache'
        self.calls = []

        def worker(binary, operation, data, **parameters):
            self.calls.append((operation, data, parameters))
            return b'payload:' + data[::-1]

        patches = [
            mock.patch.object(codec, '_rust_compressor_path', lambda: self.binary),
            mock.patch.object(codec, '_worker_request', worker),
            mock.patch.dict(os.environ, {codec.ENV_COMPRESSION_CACHE: str(self.cache)}),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        os.environ.pop(ENV_REHASH, None)
        self.addCleanup(self.temp.cleanup)

    def encode(self, data=b'abcdef', chain=1024):
        return codec._rust_payload(data, window_size=4096, min_match_length=3,
                                   search_chain=chain, lazy_bias=1)

    def test_identical_request_reuses_payload(self):
        first = self.encode()
        self.assertEqual(self.encode(), first)
        self.assertEqual(len(self.calls), 1)

    def test_parameters_and_input_are_part_of_the_key(self):
        self.encode()
        self.encode(chain=64)
        self.encode(data=b'abcdeg')
        self.assertEqual(len(self.calls), 3)

    def test_corrupt_entry_is_recomputed(self):
        first = self.encode()
        entry = next(path for path in self.cache.glob('??/*'))
        entry.write_bytes(entry.read_bytes()[:-1] + b'X')
        self.assertEqual(self.encode(), first)
        self.assertEqual(len(self.calls), 2)

    def test_rehash_bypasses_reads(self):
        self.encode()
        with mock.patch.dict(os.environ, {ENV_REHASH: '1'}):
            self.encode()
        self.assertEqual(len(self.calls), 2)

    def test_disabled_without_store(self):
        with mock.patch.dict(os.environ):
            os.environ.pop(codec.ENV_COMPRESSION_CACHE)
            self.encode()
            self.encode()
        self.assertEqual(len(self.calls), 2)
        self.assertFalse(self.cache.exists())

    def test_prune_keeps_most_recent_entries(self):
        for index in range(4):
            self.encode(data=bytes([index]) * 100)
        entries = sorted(self.cache.glob('??/*'), key=lambda path: path.stat().st_mtime_ns)
        for age, path in enumerate(entries):
            os.utime(path, ns=(age * 10**9, age * 10**9))
        size = entries[0].stat().st_size
        self.assertEqual(codec.prune_compression_cache(self.cache, max_bytes=2 * size), 2)
        self.assertEqual(sorted(self.cache.glob('??/*')), sorted(entries[2:]))


if __name__ == '__main__':
    unittest.main()
