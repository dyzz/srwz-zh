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
