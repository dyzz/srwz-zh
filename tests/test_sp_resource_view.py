import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from special_disc.resource_view import ResourceView


class ResourceViewTests(unittest.TestCase):
    def test_layered_member_and_catalog_writes_match_final_disc(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            retail = directory / "retail.iso"
            retail.write_bytes(b"abcdefghijklmnop")
            base = ResourceView.create(directory / "baseline.spview", retail)
            with base.open("r+b") as stream:
                stream.seek(3)
                stream.write(b"12345")
            base.save()
            region = ResourceView.create(directory / "region.spview", base)
            with region.open("r+b") as stream:
                stream.seek(6)
                stream.write(b"xy")
                stream.seek(2, 2)
                stream.write(b"zz")
            region.save()
            restored = ResourceView.load(region.path)
            expected = b"abc123xyijklmnop\0\0zz"
            self.assertEqual(restored.digest(), hashlib.sha256(expected).hexdigest())
            with restored.open("rb") as stream:
                stream.seek(4)
                self.assertEqual(stream.read(6), b"23xyij")
            out = directory / "published.iso"
            restored.materialize(out)
            self.assertEqual(out.read_bytes(), expected)
            self.assertEqual(retail.read_bytes(), b"abcdefghijklmnop")
            restored.spans[-1][2].write_bytes(b"")
            with self.assertRaisesRegex(ValueError, "truncated resource"):
                restored.digest()


class DigestMemoTests(unittest.TestCase):
    def test_saved_view_carries_its_digest_until_a_blob_changes(self):
        import json
        import os
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            retail = directory / "retail.iso"
            retail.write_bytes(b"abcdefghijklmnop")
            base = ResourceView.create(directory / "baseline.spview", retail)
            with base.open("r+b") as stream:
                stream.seek(3)
                stream.write(b"12345")
            base.digest()
            base.save()
            region = ResourceView.create(directory / "region.spview", base)
            with region.open("r+b") as stream:
                stream.seek(6)
                stream.write(b"xy")
            region.save()                               # digest not known yet: nothing to carry
            self.assertNotIn("sha256", json.loads(region.path.read_text()))
            expected = hashlib.sha256(b"abc123xyijklmnop").hexdigest()
            self.assertEqual(region.digest(), expected)  # hashed once, written back to the saved view
            self.assertEqual(json.loads(region.path.read_text())["sha256"], expected)
            loaded = ResourceView.load(region.path)
            self.assertEqual(loaded.known_digest(), expected)
            self.assertEqual(loaded.digest(recompute=True), expected)
            with loaded.open("r+b") as stream:           # a write drops what was known
                stream.seek(0)
                stream.write(b"Z")
            self.assertIsNone(loaded.known_digest())
            blob = region.spans[0][2]
            blob.write_bytes(b"XY")                      # same size, new content and mtime
            os.utime(blob, ns=(1, 1))
            reloaded = ResourceView.load(region.path)
            self.assertIsNone(reloaded.known_digest())
            self.assertEqual(reloaded.digest(), hashlib.sha256(b"abc123XYijklmnop").hexdigest())

    def test_pointer_scan_matches_word_by_word_search(self):
        import struct
        from special_disc.writeback.pointer_scan import sites_into
        data = bytearray(4099)
        for site in (8, 400, 4092):
            struct.pack_into("<I", data, site, 0x1000500)
        struct.pack_into("<I", data, 1200, 0x1000504)
        struct.pack_into("<I", data, 2000, 5)
        self.assertEqual(sites_into(data, 0x1000000, 0x500, 4), ([8, 400, 4092], False))
        self.assertEqual(sites_into(data, 0x1000000, 0x500, 16), ([8, 400, 1200, 4092], True))
        self.assertEqual(sites_into(bytes(data), 0x1000000, 0x9000, 4), ([], False))
