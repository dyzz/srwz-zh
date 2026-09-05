"""Thread-local Rust codec processes with framed, in-memory requests."""

from __future__ import annotations

import atexit
import os
import struct
import subprocess
import threading
import weakref
from pathlib import Path


REQUEST = struct.Struct("<8s7Q")
RESPONSE = struct.Struct("<8s2Q")
MAX_FRAME_SIZE = 512 * 1024 * 1024
NO_LAZY_BIAS = 0xFFFFFFFFFFFFFFFF
_local = threading.local()
_workers = weakref.WeakSet()
_registry_lock = threading.Lock()


class CodecWorkerError(RuntimeError):
    """The codec rejected a complete request."""


def _read_exact(stream, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = stream.read(size - len(chunks))
        if not chunk:
            raise RuntimeError("Rust codec worker returned a truncated response")
        chunks.extend(chunk)
    return bytes(chunks)


class _Worker:
    def __init__(self, binary: Path, identity: tuple):
        self.owner_pid = os.getpid()
        self.identity = identity
        self.process = None
        self.process = subprocess.Popen(
            [str(binary), "worker-stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        with _registry_lock:
            _workers.add(self)

    def close(self):
        process = self.process
        if process is None:
            return
        self.process = None
        if self.owner_pid == os.getpid():
            if process.poll() is None:
                process.terminate()
            process.wait()
        for stream in (process.stdin, process.stdout):
            try:
                stream.close()
            except OSError:
                pass

    def __del__(self):
        self.close()

    def request(self, header: bytes, data: bytes) -> bytes:
        self.process.stdin.write(header)
        self.process.stdin.write(data)
        self.process.stdin.flush()
        magic, status, size = RESPONSE.unpack(
            _read_exact(self.process.stdout, RESPONSE.size)
        )
        if magic != b"SRWZR001" or status not in (0, 1) or size > MAX_FRAME_SIZE:
            raise RuntimeError("Rust codec worker response contract drift")
        result = _read_exact(self.process.stdout, size)
        if status:
            raise CodecWorkerError(result.decode("utf-8", errors="replace"))
        return result


def request(binary: Path, operation: int, data: bytes, *, window_size: int = 0,
            prefix_size: int = 0, min_match_length: int = 0,
            search_chain: int = 0, lazy_bias: int | None = None) -> bytes:
    if len(data) > MAX_FRAME_SIZE:
        raise ValueError("Rust codec worker input exceeds frame limit")
    stat = binary.stat()
    identity = (str(binary), stat.st_ino, stat.st_size, stat.st_mtime_ns,
                stat.st_ctime_ns, os.getpid())
    worker = getattr(_local, "worker", None)
    if (worker is None or worker.identity != identity or worker.process is None
            or worker.process.poll() is not None):
        if worker is not None:
            worker.close()
        worker = _Worker(binary, identity)
        _local.worker = worker
    header = REQUEST.pack(b"SRWZQ001", operation, len(data), window_size,
                          prefix_size, min_match_length, search_chain,
                          NO_LAZY_BIAS if lazy_bias is None else lazy_bias)
    try:
        return worker.request(header, data)
    except CodecWorkerError:
        # A framed codec error leaves the process synchronized for the next job.
        raise
    except (OSError, RuntimeError) as error:
        worker.close()
        _local.worker = None
        raise RuntimeError(
            "Rust codec worker failed; rebuild the codec with "
            "`python3 tools/build_rust_compressor.py --force`"
        ) from error


@atexit.register
def close_workers():
    with _registry_lock:
        workers = list(_workers)
    for worker in workers:
        worker.close()
    _local.worker = None
