from __future__ import annotations

import io
import os
import socket
import tempfile
import threading
import unittest
from pathlib import Path

from tools.srwz.armsx2_runtime import (
    Armsx2RuntimeError,
    Armsx2Session,
    parse_reply,
    prepare_session_data,
    read_reply,
    runner_argv,
)


class FakeRunner:
    """Serve canned replies on a unix socket, recording the commands received."""

    def __init__(self, path: str, replies: dict[str, list[str]]):
        self.path = path
        self.replies = replies
        self.received: list[str] = []
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(path)
        self.server.listen(1)
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self) -> None:
        conn, _ = self.server.accept()
        stream = conn.makefile("rw")
        for line in stream:
            command = line.strip()
            self.received.append(command)
            rows = self.replies.get(command.split()[0], ["OK frame=0"])
            stream.write("\n".join(rows) + "\n")
            stream.flush()
            if command == "quit":
                break
        conn.close()
        self.server.close()


class Armsx2RuntimeTests(unittest.TestCase):
    def test_runner_argv_keeps_session_files_in_outdir(self) -> None:
        outdir = Path("/tmp/session")
        argv = runner_argv(
            Path("/iso/sp.iso"), Path("/cards/Mcd001.ps2"), outdir, "/tmp/s.sock",
            bios=outdir / "armsx2-data/bios/b.bin", renderer="metal", upscale=2,
            runner_dir=Path("/runner"),
        )
        self.assertEqual(argv[0], "/runner/pcsx2-srwzrunner")
        options = dict(zip(argv[1::2], argv[2::2]))
        self.assertEqual(options["--data"], "/tmp/session/armsx2-data")
        self.assertEqual(options["--outdir"], "/tmp/session")
        self.assertEqual(options["--resources"], "/runner/resources")
        self.assertEqual(options["--renderer"], "metal")
        self.assertEqual(options["--upscale"], "2")

    def test_runner_argv_rejects_unknown_renderer(self) -> None:
        with self.assertRaises(Armsx2RuntimeError):
            runner_argv(Path("a"), Path("b"), Path("c"), "s", bios=Path("d"), renderer="vulkan")

    def test_prepare_session_data_copies_bios_family(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bios_dir = Path(tmp) / "bios"
            bios_dir.mkdir()
            for name in ("B.bin", "B.NVM", "B.MEC", "Other.bin"):
                (bios_dir / name).write_bytes(name.encode())
            outdir = Path(tmp) / "out"
            bios = prepare_session_data(outdir, bios_dir=bios_dir, bios_name="B.bin")
            self.assertEqual(bios, outdir / "armsx2-data" / "bios" / "B.bin")
            self.assertEqual(sorted(p.name for p in bios.parent.iterdir()), ["B.MEC", "B.NVM", "B.bin"])
            # The session copy is independent of the source.
            (bios.parent / "B.NVM").write_bytes(b"changed")
            self.assertEqual((bios_dir / "B.NVM").read_bytes(), b"B.NVM")

    def test_prepare_session_data_requires_bios(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(Armsx2RuntimeError):
                prepare_session_data(Path(tmp) / "out", bios_dir=Path(tmp), bios_name="missing.bin")

    def test_read_and_parse_reply(self) -> None:
        stream = io.StringIO("WATCH frame 3 0x10: 00 -> 01\nOK frame=4\nOK frame=5\n")
        reply = parse_reply(read_reply(stream), "run 2")
        self.assertEqual(reply.lines, ["WATCH frame 3 0x10: 00 -> 01"])
        self.assertEqual(reply.frame, 4)
        with self.assertRaisesRegex(Armsx2RuntimeError, "bad address"):
            parse_reply(["ERR bad address 'zz'"], "mem zz 4")
        with self.assertRaises(Armsx2RuntimeError):
            read_reply(io.StringIO("SHOT x\n"))

    def test_video_path_roundtrip_and_command_injection_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sock = os.path.join(tmp, "v.sock")
            result = Path(tmp) / "battle with spaces.mp4"
            fake = FakeRunner(sock, {"video": [f"VIDEO {result}", "OK frame=123"]})
            session = Armsx2Session(Path("a.iso"), Path("c.ps2"), Path(tmp), socket_path=sock)
            session._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            session._socket.connect(sock)
            session._stream = session._socket.makefile("rw")
            session.start_video("battle with spaces.mp4")
            self.assertEqual(session.stop_video(), result)
            self.assertEqual(session.frame, 123)
            for bad in ("", "x\nquit", "x\rquit"):
                with self.assertRaises(ValueError):
                    session.start_video(bad)
            session.close()
            fake.thread.join(5)
            self.assertEqual(fake.received, ["video start battle with spaces.mp4", "video stop", "quit"])

    def test_session_speaks_the_line_protocol(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sock = os.path.join(tmp, "r.sock")
            fake = FakeRunner(sock, {
                "run": ["OK frame=10"],
                "shot": [f"SHOT {tmp}/title.png 640x448 luma=12.0", "OK frame=10"],
                "poke": ["ERR addr out of range (size 0x2000000)"],
                "quit": ["OK frame=10"],
            })
            session = Armsx2Session(Path("a.iso"), Path("c.ps2"), Path(tmp), socket_path=sock)
            session._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            session._socket.connect(sock)
            session._stream = session._socket.makefile("rw")

            self.assertEqual(session.run(10).frame, 10)
            self.assertEqual(session.frame, 10)
            self.assertEqual(session.shot("title"), Path(tmp) / "title.png")
            with self.assertRaisesRegex(Armsx2RuntimeError, "out of range"):
                session.cmd("poke 3000000 00")
            session.close()
            fake.thread.join(5)
            self.assertEqual(fake.received, ["run 10", "shot title", "poke 3000000 00", "quit"])


if __name__ == "__main__":
    unittest.main()
