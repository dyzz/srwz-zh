import ctypes
import platform
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.srwz import codec


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_ROOT / "tools/native/srwz_maximum_match.c"


class MaximumMatchAcceleratorTests(unittest.TestCase):
    def test_native_table_matches_python_fallback_exactly(self):
        compiler = shutil.which("clang")
        if compiler is None:
            self.skipTest("clang is not installed")
        system = platform.system()
        if system == "Darwin":
            suffix = ".dylib"
            link_flags = ["-dynamiclib"]
        elif system == "Linux":
            suffix = ".so"
            link_flags = ["-shared", "-fPIC"]
        else:
            self.skipTest(f"unsupported accelerator host: {system}")

        source = (
            bytes(range(64))
            + (b"ABRACADABRA" * 80)
            + bytes(range(63, -1, -1))
            + (b"\0" * 256)
        )
        arguments = {
            "window_size": 1024,
            "min_match_length": 2,
            "max_match_chain": 65535,
            "prefix_size": 97,
        }
        with mock.patch.object(
            codec,
            "_maximum_match_library",
            return_value=None,
        ):
            expected = codec._maximum_match_table(source, **arguments)

        with tempfile.TemporaryDirectory() as temporary:
            library_path = Path(temporary) / f"libsrwz{suffix}"
            subprocess.run(
                [
                    compiler,
                    "-std=c11",
                    "-O3",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-pthread",
                    *link_flags,
                    str(SOURCE),
                    "-o",
                    str(library_path),
                ],
                check=True,
                cwd=PROJECT_ROOT,
                capture_output=True,
            )
            library = ctypes.CDLL(str(library_path))
            with mock.patch.object(
                codec,
                "_maximum_match_library",
                return_value=library,
            ):
                actual = codec._maximum_match_table(source, **arguments)

        self.assertEqual(
            tuple(actual[0]),
            tuple(expected[0]),
        )
        self.assertEqual(
            tuple(actual[1]),
            tuple(expected[1]),
        )
        self.assertEqual(
            tuple(actual[2]),
            tuple(expected[2]),
        )


if __name__ == "__main__":
    unittest.main()
