"""Execute production IOP/EE drain code with deterministic libsd interleavings.

ASan/UBSan check host memory safety. Hardware timing remains an ARMSX2/PS2 test.
Only platform glue (headers, disc server, IRX startup) is excluded from compilation.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tools/special_disc/vocal_bgm"


class VocalPcmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which(os.environ.get("CC", "cc"))
        if compiler is None:
            raise unittest.SkipTest("host C compiler required")
        cls.tmp = tempfile.TemporaryDirectory(prefix="vocal-pcm-test-")
        cls.addClassCleanup(cls.tmp.cleanup)
        out = Path(cls.tmp.name)
        pcm = (SOURCE / "iop/pcm.c").read_text()
        # Compile these functions verbatim, never a Python rewrite of the algorithm.
        parts = [pcm[pcm.index("#define BLOCK"):pcm.index("static int wrap_cdread")],
                 pcm[pcm.index("static unsigned now"):pcm.index("/* Redirect every")],
                 pcm[pcm.index("static void *dispatch"):pcm.index("static void rpc")]]
        (out / "pcm-under-test.inc").write_text("\n".join(parts))
        ee = (SOURCE / "player.c").read_text()
        (out / "drain-under-test.inc").write_text(
            ee[ee.index("static void pump_drain"):ee.index("void player_pump")])
        cls.binary = out / "pcm-test"
        subprocess.run([compiler, "-O1", "-g", "-fsanitize=address,undefined",
                        "-fno-sanitize-recover=all", "-Wno-pointer-to-int-cast",
                        "-I", str(out), str(ROOT / "tests/fixtures/vocal_pcm_host.c"),
                        "-o", str(cls.binary)], check=True, capture_output=True, text=True)

    def run_case(self, name):
        result = subprocess.run([str(self.binary), name], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


def _case(name):
    def test(self):
        self.run_case(name)
    return test


for _name in ("halt", "ring", "tail_home", "busy_tail", "restart_grace",
              "handler_race", "stop_race", "failed_start", "stale_signals",
              "stop_reset", "short_once"):
    setattr(VocalPcmTests, "test_" + _name, _case(_name))

if __name__ == "__main__":
    unittest.main()
