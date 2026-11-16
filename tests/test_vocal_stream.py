"""Run the player's stream core (ring + loop buffer + ov_raw_pcm_seek) on the host.

The core is copied verbatim out of player.c and linked against host-built Tremor
plus seek.c, exactly the decoder sources the EE payload uses. Each case feeds a
real Ogg Vorbis file through simulated disc reads with random latency and long
stalls, and compares every output frame with a straight whole-file decode laid
out as the game hears it: the first pass to the loop end, then loop start to
loop end again and again. Needs a host C compiler, libogg headers, ffmpeg with
the libvorbis encoder (tests/fixtures/vorbis_encode_host.c, libvorbis VBR q0 as on the
music page) and the pinned Tremor checkout under work/toolchain.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tools/special_disc/vocal_bgm"
RATE = 48000


def _tremor() -> Path | None:
    for path in sorted((ROOT / "work/toolchain").glob("ps2-libtremor-*")):
        if (path / "vorbisfile.c").exists():
            return path
    return None


def _ogg_include() -> Path | None:
    for prefix in (os.environ.get("OGG_PREFIX"), "/opt/homebrew", "/usr/local", "/usr"):
        if prefix and (Path(prefix) / "include/ogg/ogg.h").exists() and (Path(prefix) / "include/vorbis/vorbisenc.h").exists():
            return Path(prefix)
    return None


class VocalStreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which(os.environ.get("CC", "cc"))
        tremor, ogg = _tremor(), _ogg_include()
        ffmpeg = shutil.which("ffmpeg")
        if not (compiler and tremor and ogg and ffmpeg):
            raise unittest.SkipTest("needs cc, Tremor under work/toolchain, libogg/libvorbis and ffmpeg")
        cls.tmp = tempfile.TemporaryDirectory(prefix="vocal-stream-test-")
        cls.addClassCleanup(cls.tmp.cleanup)
        out = cls.dir = Path(cls.tmp.name)
        player = (SOURCE / "player.c").read_text()
        core = player[player.index("/* ---- stream core"):player.index("/* ---- end of stream core")]
        (out / "stream-under-test.inc").write_text(core)
        shutil.copyfile(SOURCE / "seek.c", out / "seek.c")
        sources = [tremor / f"{n}.c" for n in "mdct block codebook floor0 floor1 info mapping0 registry res012 sharedbook synthesis window".split()]
        cls.binary = out / "vocal-stream"
        include = ["-I", str(out), "-I", str(tremor), "-I", str(ogg / "include")]
        # Upstream Tremor is built plainly (UBSan flags its own shifts); the player core is sanitized.
        objects = []
        for src in [out / "seek.c", *sources]:
            obj = out / (src.stem + ".o")
            subprocess.run([compiler, "-O1", "-g", "-w", *include, "-c", str(src), "-o", str(obj)],
                           check=True, capture_output=True, text=True)
            objects.append(str(obj))
        subprocess.run([compiler, "-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                        "-Wall", "-Wno-unused-function", "-Wno-unused-variable", *include,
                        str(ROOT / "tests/fixtures/vocal_stream_host.c"), *objects,
                        "-L", str(ogg / "lib"), "-logg", "-o", str(cls.binary)],
                       check=True, capture_output=True, text=True)
        cls.encoder = out / "vorbis-encode"
        subprocess.run([compiler, "-O2", "-w", "-I", str(ogg / "include"), str(ROOT / "tests/fixtures/vorbis_encode_host.c"),
                        "-L", str(ogg / "lib"), "-lvorbisenc", "-lvorbis", "-logg", "-o", str(cls.encoder)],
                       check=True, capture_output=True, text=True)
        cls.songs = {}

    @classmethod
    def song(cls, name, seconds, layout):
        """Encode a test song the way the music page does (48 kHz stereo, q0)."""
        if name in cls.songs:
            return cls.songs[name]
        path = cls.dir / f"{name}.ogg"
        inputs, filters = [], []
        for i, (kind, length) in enumerate(layout):
            src = {"sweep": f"sine=frequency=220:beep_factor=3:duration={length}",
                   "noise": f"anoisesrc=d={length}:c=pink:a=0.4",
                   "silence": f"anullsrc=r={RATE}:cl=stereo:d={length}",
                   "tone": f"sine=frequency=880:duration={length}"}[kind]
            inputs += ["-f", "lavfi", "-i", src]
            filters.append(f"[{i}:a]aresample={RATE},aformat=sample_fmts=fltp:channel_layouts=stereo[a{i}]")
        graph = ";".join(filters) + ";" + "".join(f"[a{i}]" for i in range(len(layout))) + f"concat=n={len(layout)}:v=0:a=1[out]"
        raw = subprocess.run(["ffmpeg", "-v", "error", *inputs, "-filter_complex", graph, "-map", "[out]",
                              "-t", str(seconds), "-ar", str(RATE), "-ac", "2", "-f", "s16le", "-"],
                             check=True, capture_output=True).stdout
        path.write_bytes(subprocess.run([str(cls.encoder)], input=raw, check=True, capture_output=True).stdout)
        ref = cls.dir / f"{name}.ref"
        result = subprocess.run([str(cls.binary), "ref", str(path), str(ref)], capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        frames = int(result.stdout.split()[1])
        data = ref.read_bytes()
        assert len(data) == frames * 4
        cls.songs[name] = (path, frames, data)
        return cls.songs[name]

    def play(self, name, seconds, layout, loop_start=None, loop_end=None, once=False, passes=3, seed=1):
        path, frames, ref = self.song(name, seconds, layout)
        start = 0 if loop_start is None else int(loop_start * RATE)
        end = frames if loop_end is None else int(loop_end * RATE)
        expect = bytearray(ref[:end * 4])
        if once:
            expect += bytes(4 * 2048 * 4)
        else:
            while len(expect) < (end + passes * (end - start)) * 4:
                expect += ref[start * 4:end * 4]
        n_out = (len(expect) // 4) // 2048 * 2048
        crc = zlib.crc32(path.read_bytes())
        out = self.dir / f"{name}-{start}-{end}-{int(once)}-{seed}.raw"
        result = subprocess.run([str(self.binary), "play", str(path), str(out), str(frames), str(start), str(end),
                                 str(int(once)), str(crc), str(n_out), str(seed)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        got = out.read_bytes()
        self.assertEqual(len(got), n_out * 4)
        if got != bytes(expect[:n_out * 4]):
            first = next(i for i in range(0, n_out * 4, 4) if got[i:i + 4] != expect[i:i + 4]) // 4
            self.fail(f"PCM differs from frame {first} ({first / RATE:.3f} s); {result.stdout}")
        self.assertIn("crc_state 1", result.stdout) if end == frames else None
        return result.stdout

    LONG = [("sweep", 40), ("silence", 8), ("noise", 60), ("tone", 20), ("noise", 70)]   # 198 s, about 1.6 MB

    def test_whole_loop_long_song(self):
        self.play("long", 198, self.LONG, passes=1)

    def test_custom_loop_late_in_long_song(self):
        self.play("long", 198, self.LONG, loop_start=150.3, loop_end=190.7, passes=4)

    def test_loop_start_inside_silence(self):
        # the loop page is chosen 6 s earlier, inside the long silent pages
        self.play("long", 198, self.LONG, loop_start=45.2, loop_end=60.5, passes=3, seed=7)

    def test_loop_start_just_after_silence(self):
        self.play("long", 198, self.LONG, loop_start=49.0, loop_end=110.0, passes=2, seed=3)

    def test_loop_start_within_first_seconds(self):
        self.play("long", 198, self.LONG, loop_start=3.0, loop_end=20.0, passes=3, seed=5)

    def test_loop_shorter_than_one_read(self):
        self.play("long", 198, self.LONG, loop_start=30.0, loop_end=30.0 + 100 / RATE, passes=30, seed=11)

    def test_once(self):
        self.play("long", 198, self.LONG, once=True)

    def test_short_song_without_tail(self):
        self.play("short", 9, [("noise", 4), ("sweep", 5)], passes=5, seed=13)

    def test_short_custom_loop(self):
        self.play("short", 9, [("noise", 4), ("sweep", 5)], loop_start=2.5, loop_end=8.0, passes=5, seed=17)


if __name__ == "__main__":
    unittest.main()
