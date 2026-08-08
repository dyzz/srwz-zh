"""Small PCSX2 PINE IPC client shared by runtime tools."""

from __future__ import annotations

import hashlib
import os
import socket
import struct
from pathlib import Path


PINE_OK = 0
PINE_READ32 = 2
PINE_READ64 = 3
PINE_VERSION = 8
PINE_TITLE = 0x0B
PINE_ID = 0x0C
PINE_STATUS = 0x0F
PINE_RUNNING = 0
DEFAULT_READ64_WORDS_PER_BATCH = 32768


class PineError(RuntimeError):
    """PCSX2 PINE returned malformed data or failed an operation."""


def request_frame(payload: bytes) -> bytes:
    return struct.pack("<I", len(payload) + 4) + payload


def read64_payload(start: int, size: int) -> bytes:
    if start < 0 or start > 0xFFFFFFFF:
        raise ValueError("PINE start address is outside 32-bit memory")
    if size < 0 or size % 8:
        raise ValueError("PINE Read64 size must be a non-negative multiple of 8")
    payload = bytearray()
    for offset in range(0, size, 8):
        address = start + offset
        if address > 0xFFFFFFFF:
            raise ValueError("PINE read range crosses 32-bit memory")
        payload.append(PINE_READ64)
        payload.extend(struct.pack("<I", address))
    return bytes(payload)


def read32_payload(start: int, size: int) -> bytes:
    if start < 0 or start > 0xFFFFFFFF:
        raise ValueError("PINE start address is outside 32-bit memory")
    if size < 0 or size % 4:
        raise ValueError("PINE Read32 size must be a non-negative multiple of 4")
    payload = bytearray()
    for offset in range(0, size, 4):
        address = start + offset
        if address > 0xFFFFFFFF:
            raise ValueError("PINE read range crosses 32-bit memory")
        payload.append(PINE_READ32)
        payload.extend(struct.pack("<I", address))
    return bytes(payload)


def parse_ok_response(packet: bytes) -> bytes:
    if len(packet) < 5:
        raise PineError("truncated PINE response")
    declared = struct.unpack_from("<I", packet)[0]
    if declared != len(packet):
        raise PineError(
            f"PINE response length {len(packet)} does not match {declared}"
        )
    if packet[4] != PINE_OK:
        raise PineError(f"PINE command failed with status 0x{packet[4]:02X}")
    return packet[5:]


class PineClient:
    def __init__(self, socket_path: Path, *, timeout: float = 15.0):
        self.socket_path = socket_path
        self.timeout = timeout

    @staticmethod
    def _receive_exact(connection: socket.socket, size: int) -> bytes:
        output = bytearray()
        while len(output) < size:
            chunk = connection.recv(size - len(output))
            if not chunk:
                raise PineError("PCSX2 closed a PINE response early")
            output.extend(chunk)
        return bytes(output)

    def transact(self, payload: bytes) -> bytes:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(self.timeout)
            connection.connect(str(self.socket_path))
            connection.sendall(request_frame(payload))
            header = self._receive_exact(connection, 4)
            declared = struct.unpack("<I", header)[0]
            if declared < 5:
                raise PineError(f"invalid PINE response size {declared}")
            packet = header + self._receive_exact(connection, declared - 4)
        return parse_ok_response(packet)

    def read32(self, address: int) -> int:
        response = self.transact(
            bytes([PINE_READ32]) + struct.pack("<I", address)
        )
        if len(response) != 4:
            raise PineError("PINE Read32 returned the wrong size")
        return struct.unpack("<I", response)[0]

    def read_bytes(self, address: int, size: int) -> bytes:
        if size < 0:
            raise ValueError("PINE byte range size must be non-negative")
        aligned_start = address & ~3
        aligned_end = (address + size + 3) & ~3
        response = self.transact(
            read32_payload(aligned_start, aligned_end - aligned_start)
        )
        expected_size = aligned_end - aligned_start
        if len(response) != expected_size:
            raise PineError(
                f"PINE Read32 batch returned {len(response)} bytes, "
                f"expected {expected_size}"
            )
        offset = address - aligned_start
        return response[offset:offset + size]

    def read_text(self, opcode: int) -> str:
        response = self.transact(bytes([opcode]))
        if len(response) < 4:
            raise PineError("PINE text response has no length")
        size = struct.unpack_from("<I", response)[0]
        value = response[4:]
        if len(value) != size or not value.endswith(b"\0"):
            raise PineError("PINE text response is malformed")
        return value[:-1].decode("utf-8", errors="strict")

    def status(self) -> int:
        response = self.transact(bytes([PINE_STATUS]))
        if len(response) != 4:
            raise PineError("PINE status returned the wrong size")
        return struct.unpack("<I", response)[0]

    def sha256_range(
        self,
        start: int,
        size: int,
        *,
        words_per_batch: int = DEFAULT_READ64_WORDS_PER_BATCH,
    ) -> str:
        if words_per_batch <= 0:
            raise ValueError("PINE batch size must be positive")
        if size % 8:
            raise ValueError("runtime range must be divisible by 8")
        digest = hashlib.sha256()
        batch_size = words_per_batch * 8
        for offset in range(0, size, batch_size):
            current_size = min(batch_size, size - offset)
            response = self.transact(
                read64_payload(start + offset, current_size)
            )
            if len(response) != current_size:
                raise PineError(
                    f"PINE Read64 returned {len(response)} bytes, "
                    f"expected {current_size}"
                )
            digest.update(response)
        return digest.hexdigest()


def default_socket_path() -> Path:
    return Path(os.environ.get("TMPDIR", "/tmp")) / "pcsx2.sock"


__all__ = [
    "PINE_ID",
    "PINE_READ32",
    "PINE_READ64",
    "PINE_RUNNING",
    "PINE_STATUS",
    "PINE_TITLE",
    "PINE_VERSION",
    "PineClient",
    "PineError",
    "default_socket_path",
    "parse_ok_response",
    "read32_payload",
    "read64_payload",
    "request_frame",
]
