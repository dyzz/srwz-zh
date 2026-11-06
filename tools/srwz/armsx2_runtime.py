"""Headless ARMSX2 sessions: launch pcsx2-srwzrunner and speak its line protocol.

The runner (armsx2-runner, branch srwz/test-runner) advances the VM only when a
command asks it to, so a command list replays to the same frames every time. The
protocol is the one tools have used with lrps2_drive.py -- run / press / hold /
release / shot / mem / poke / watch / state -- plus load, dump, perf and the probes
(trace / untrace / traces / tracedump, storewatch / unstorewatch, audio / voices). Every reply ends
with an "OK frame=N" or "ERR ..." line.

Differences from LRPS2 that matter to callers: savestates are ARMSX2 .p2s, and the
memory card is copied to OUTDIR/save/Mcd001.ps2 (the source card is never written).
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNNER_DIR = Path(
    os.environ.get(
        "SRWZ_ARMSX2_RUNNER_DIR",
        PROJECT_ROOT.parent / "armsx2-runner" / "build" / "macos-runner" / "pcsx2-srwzrunner",
    )
)
# The BIOS LRPS2 boots, so both runtimes start from the same firmware.
BIOS_DIR = PROJECT_ROOT / "work" / "runtime" / "lrps2" / "system" / "pcsx2" / "bios"
BIOS_NAME = "PS2 Bios 30004R V6 Pal.bin"
RENDERERS = ("sw", "metal", "null")


class Armsx2RuntimeError(RuntimeError):
    """The runner failed to start, or a command answered ERR."""


def clone_file(source: Path, destination: Path) -> None:
    """APFS clone (cp -c) so per-session copies cost no space; plain copy elsewhere."""

    if destination.exists() or destination.is_symlink():
        destination.unlink()
    result = subprocess.run(
        ["cp", "-c", str(source), str(destination)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0:
        shutil.copy2(source, destination)


def prepare_session_data(
    outdir: Path, *, bios_dir: Path = BIOS_DIR, bios_name: str = BIOS_NAME
) -> Path:
    """Create OUTDIR/armsx2-data with its own BIOS copy; return the BIOS path.

    The emulator writes the BIOS NVM next to the BIOS, so it gets a session copy.
    """

    bios_source = bios_dir / bios_name
    if not bios_source.is_file():
        raise Armsx2RuntimeError(f"BIOS not found: {bios_source}")
    bios = outdir / "armsx2-data" / "bios"
    bios.mkdir(parents=True, exist_ok=True)
    for source in bios_dir.glob(Path(bios_name).stem + ".*"):
        clone_file(source, bios / source.name)
    return bios / bios_name


def runner_argv(
    iso: Path,
    card: Path,
    outdir: Path,
    socket_path: str,
    *,
    bios: Path,
    renderer: str = "sw",
    upscale: int = 1,
    runner_dir: Path = RUNNER_DIR,
    extra: Sequence[str] = (),
) -> list[str]:
    """Return the pcsx2-srwzrunner command line for one session."""

    if renderer not in RENDERERS:
        raise Armsx2RuntimeError(f"renderer must be one of {', '.join(RENDERERS)}")
    if upscale < 1:
        raise Armsx2RuntimeError("upscale must be at least 1")
    return [
        str(runner_dir / "pcsx2-srwzrunner"),
        "--iso", str(iso),
        "--memcard", str(card),
        "--outdir", str(outdir),
        "--socket", socket_path,
        "--data", str(outdir / "armsx2-data"),
        "--bios", str(bios),
        "--resources", str(runner_dir / "resources"),
        "--renderer", renderer,
        "--upscale", str(upscale),
        *extra,
    ]


def read_reply(stream) -> list[str]:
    """Read one reply: lines up to and including the OK/ERR line."""

    rows = []
    while True:
        line = stream.readline()
        if not line:
            raise Armsx2RuntimeError("runner closed the connection mid-reply")
        line = line.rstrip("\n")
        rows.append(line)
        if line.startswith(("OK", "ERR")):
            return rows


@dataclass
class Reply:
    lines: list[str]  # everything before the final status line
    frame: int


def parse_reply(rows: list[str], command: str) -> Reply:
    status = rows[-1]
    if status.startswith("ERR"):
        raise Armsx2RuntimeError(f"{command!r}: {status[4:]}")
    frame = -1
    if status.startswith("OK frame="):
        frame = int(status[len("OK frame="):])
    return Reply(lines=rows[:-1], frame=frame)


class Armsx2Session:
    """One running pcsx2-srwzrunner, as a context manager.

    with Armsx2Session(iso, card, outdir) as vm:
        vm.cmd("run 1800")
        vm.cmd("press start 3")
        vm.cmd("shot title")
    """

    def __init__(
        self,
        iso: Path,
        card: Path,
        outdir: Path,
        *,
        socket_path: str | None = None,
        renderer: str = "sw",
        upscale: int = 1,
        runner_dir: Path = RUNNER_DIR,
        startup_timeout: float = 120.0,
        command_timeout: float = 600.0,
    ):
        self.iso = Path(iso).resolve()
        self.card = Path(card).resolve()
        self.outdir = Path(outdir).resolve()
        self.socket_path = socket_path or f"/tmp/srwz-armsx2-{os.getpid()}-{id(self):x}.sock"
        self.renderer = renderer
        self.upscale = upscale
        self.runner_dir = runner_dir
        self.startup_timeout = startup_timeout
        self.command_timeout = command_timeout
        self.process: subprocess.Popen | None = None
        self._socket: socket.socket | None = None
        self._stream = None
        self.frame = 0

    def __enter__(self) -> "Armsx2Session":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def start(self) -> None:
        runner = self.runner_dir / "pcsx2-srwzrunner"
        if not runner.is_file():
            raise Armsx2RuntimeError(
                f"runner not built: {runner} (armsx2-runner/pcsx2-srwzrunner/build-macos.sh)"
            )
        self.outdir.mkdir(parents=True, exist_ok=True)
        bios = prepare_session_data(self.outdir)
        Path(self.socket_path).unlink(missing_ok=True)
        argv = runner_argv(
            self.iso, self.card, self.outdir, self.socket_path,
            bios=bios, renderer=self.renderer, upscale=self.upscale, runner_dir=self.runner_dir,
        )
        log = (self.outdir / "runner.log").open("w")
        self.process = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + self.startup_timeout
        while not Path(self.socket_path).exists():
            if self.process.poll() is not None:
                raise Armsx2RuntimeError(
                    f"runner exited with {self.process.returncode}; see {self.outdir / 'runner.log'}"
                )
            if time.monotonic() > deadline:
                self.close()
                raise Armsx2RuntimeError("runner did not open its socket in time")
            time.sleep(0.05)
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._socket.settimeout(self.command_timeout)
        self._socket.connect(self.socket_path)
        self._stream = self._socket.makefile("rw")

    def cmd(self, command: str) -> Reply:
        """Send one command and return its reply; raise on ERR."""

        if self._stream is None:
            raise Armsx2RuntimeError("session is not started")
        self._stream.write(command + "\n")
        self._stream.flush()
        reply = parse_reply(read_reply(self._stream), command)
        if reply.frame >= 0:
            self.frame = reply.frame
        return reply

    def run(self, frames: int) -> Reply:
        return self.cmd(f"run {frames}")

    def press(self, button: str, frames: int = 3) -> Reply:
        return self.cmd(f"press {button} {frames}")

    def shot(self, name: str) -> Path:
        line = self.cmd(f"shot {name}").lines[-1]
        return Path(line.split()[1])

    def start_video(self, path: str | Path) -> Reply:
        """Record each advanced frame and SPU2 audio; requires ffmpeg on PATH.

        Relative paths are under outdir; .mp4 is appended if absent. Existing
        output is never overwritten. Audio capture and state loading are blocked
        until stop_video(). The runner captures at its native refresh rate.
        """
        name = str(path)
        if not name or "\n" in name or "\r" in name:
            raise ValueError("video path must be nonempty and contain no newlines")
        return self.cmd(f"video start {name}")

    def stop_video(self) -> Path:
        """Finalize H.264/AAC MP4, retaining source WAV and timing JSON beside it."""
        reply = self.cmd("video stop")
        for line in reply.lines:
            if line.startswith("VIDEO "):
                return Path(line.removeprefix("VIDEO "))
        raise Armsx2RuntimeError("video stop returned no output path")

    def read_ram(self, address: int, length: int) -> bytes:
        """Read EE RAM through a binary dump (no hex text for large ranges)."""

        path = self.outdir / f".ram-{address:08x}-{length}.bin"
        self.cmd(f"dump {address:x} {length} {path}")
        try:
            return path.read_bytes()
        finally:
            path.unlink(missing_ok=True)

    def close(self) -> None:
        if self._stream is not None:
            try:
                self._stream.write("quit\n")
                self._stream.flush()
                read_reply(self._stream)
            except (OSError, Armsx2RuntimeError):
                pass
            self._stream = None
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        if self.process is not None:
            try:
                self.process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            self.process = None
        Path(self.socket_path).unlink(missing_ok=True)
