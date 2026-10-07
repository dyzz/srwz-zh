"""rust-patch keeps native tokens and fits an edit into the original allocation."""
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from srwz import codec


@unittest.skipUnless(codec._rust_compressor_path().is_file(), "build the Rust codec first")
class RustPatchTests(unittest.TestCase):
    def setUp(self):
        rng = random.Random(20261007)
        words = [w.encode() for w in 'plain forest mountain sea city base desert space river road'.split()]
        data = bytearray()
        while len(data) < 200_000:
            data += rng.choice(words) + b' '
        self.data = bytes(data)
        # A weaker "native" stream that fills its allocation exactly.
        self.native = codec.encode(self.data, strategy='greedy', min_match_length=6, max_match_chain=2)

    def patch(self, modified, limit):
        return codec.reencode_changed_suffix(self.native, modified, strategy='rust-patch',
                                             min_match_length=2, max_match_chain=1024,
                                             max_output_size=limit)

    def test_edit_fits_the_native_allocation_and_decodes_exactly(self):
        modified = bytearray(self.data)
        modified[120_000:120_004] = b'SEA!'
        modified[150_000:150_006] = b'RIVER!'
        patched = self.patch(bytes(modified), len(self.native))
        self.assertLessEqual(len(patched), len(self.native))
        self.assertEqual(codec.decode_production(patched).output, bytes(modified))
        # Untouched leading blocks keep the native bytes.
        header = codec.decode_production(self.native).header_size
        self.assertEqual(patched[:header + 16], self.native[:header + 16])

    def test_unchanged_output_returns_the_native_stream(self):
        self.assertEqual(self.patch(self.data, len(self.native)), self.native)

    def test_size_change_falls_back_to_full_fit(self):
        modified = self.data + b'tail'
        rebuilt = self.patch(modified, len(self.native) + 64)
        self.assertEqual(codec.decode_production(rebuilt).output, modified)


if __name__ == '__main__':
    unittest.main()
