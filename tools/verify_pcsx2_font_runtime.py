#!/usr/bin/env python3
"""Verify the game's decoded canary font through PCSX2 PINE IPC."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import struct
from pathlib import Path

try:
    from srwz.diagnostics import require_work_output
    from srwz.project import (
        ProjectConfigError,
        load_build_profile,
        validate_profile_encoding,
    )
    from srwz.text import encode_text, load_text_table
except ModuleNotFoundError:
    from tools.srwz.diagnostics import require_work_output
    from tools.srwz.project import (
        ProjectConfigError,
        load_build_profile,
        validate_profile_encoding,
    )
    from tools.srwz.text import encode_text, load_text_table


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = (
    PROJECT_ROOT / "config" / "canary" / "minimal-slps-font.json"
)
DEFAULT_OUTPUT = (
    WORK_ROOT
    / "runtime"
    / "canary-menu"
    / "pine"
    / "font-runtime-validation.json"
)

PINE_OK = 0
PINE_READ32 = 2
PINE_READ64 = 3
PINE_VERSION = 8
PINE_TITLE = 0x0B
PINE_ID = 0x0C
PINE_STATUS = 0x0F
PINE_RUNNING = 0

FONT_SIZE_ADDRESS = 0x003F7D68
FONT_POINTER_ADDRESS = 0x0046E3A8
DECOMPRESSOR_CORE_ADDRESS = 0x001C6D70
LITERAL_COPY_LOOP_ADDRESS = 0x001C6DE8
EXPECTED_CORE_WORD = 0x00C51821
EXPECTED_LITERAL_COPY_WORD = 0x90870000
DEFAULT_READ64_WORDS_PER_BATCH = 32768
ELF_VIRTUAL_FILE_DELTA = 0x000FE580


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
        payload = bytes([PINE_READ32]) + struct.pack("<I", address)
        response = self.transact(payload)
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read the complete decoded font from a running PCSX2 instance "
            "and compare its SHA-256 with the static canary lock."
        )
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--socket", type=Path, default=default_socket_path())
    parser.add_argument("--json-output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = require_work_output(args.json_output, WORK_ROOT)
    if output.exists() and not args.force:
        raise SystemExit(f"output exists; use --force: {output}")

    config = json.loads(args.config.read_text(encoding="utf-8"))
    expected_size = int(config["font_segment"]["decoded_size"])
    expected_sha256 = config["expected_outputs"]["decoded_font_sha256"]
    table = load_text_table(
        PROJECT_ROOT / config["inputs"]["text_table"]["path"]
    )
    try:
        selection = load_build_profile(
            PROJECT_ROOT,
            PROJECT_ROOT / config["profile"],
        )
        surface = selection.single_surface()
        decision = selection.translation_for(surface.entry_id)
        profile_validation = validate_profile_encoding(selection, table)
    except (KeyError, ProjectConfigError) as error:
        raise SystemExit(f"invalid canary build profile: {error}") from error
    character_overrides = selection.character_overrides
    expected_opening_text = encode_text(
        decision.translation,
        table,
        overrides=character_overrides,
        terminate=True,
    )
    opening_offsets = surface.offsets
    if len(opening_offsets) != 1:
        raise SystemExit("opening canary must have exactly one SLPS offset")
    opening_text_address = opening_offsets[0] + ELF_VIRTUAL_FILE_DELTA
    client = PineClient(args.socket)

    version = client.read_text(PINE_VERSION)
    title = client.read_text(PINE_TITLE)
    game_id = client.read_text(PINE_ID)
    status_before = client.status()
    runtime_size = client.read32(FONT_SIZE_ADDRESS)
    runtime_pointer = client.read32(FONT_POINTER_ADDRESS)
    core_word = client.read32(DECOMPRESSOR_CORE_ADDRESS)
    literal_copy_word = client.read32(LITERAL_COPY_LOOP_ADDRESS)
    runtime_opening_text = client.read_bytes(
        opening_text_address,
        len(expected_opening_text),
    )
    runtime_sha256 = client.sha256_range(runtime_pointer, runtime_size)
    status_after = client.status()

    checks = {
        "game_id": game_id == "SLPS-25887",
        "running_before": status_before == PINE_RUNNING,
        "running_after": status_after == PINE_RUNNING,
        "decoded_size": runtime_size == expected_size,
        "decoded_sha256": runtime_sha256 == expected_sha256,
        "decompressor_core_word": core_word == EXPECTED_CORE_WORD,
        "literal_copy_loop_word": (
            literal_copy_word == EXPECTED_LITERAL_COPY_WORD
        ),
        "opening_text": runtime_opening_text == expected_opening_text,
    }
    report = {
        "schema_version": 1,
        "status": "passed" if all(checks.values()) else "failed",
        "content_policy": (
            "Runtime addresses, instruction words, sizes and hashes only; "
            "no game bytes are saved."
        ),
        "production_inputs": selection.to_metadata(),
        "profile_validation": profile_validation,
        "transport": {
            "protocol": "PCSX2 PINE IPC",
            "socket": str(args.socket),
        },
        "emulator": {
            "version": version,
            "title": title,
            "game_id": game_id,
            "status_before": status_before,
            "status_after": status_after,
        },
        "game_decompressor": {
            "core_address": f"0x{DECOMPRESSOR_CORE_ADDRESS:08X}",
            "core_word": f"0x{core_word:08X}",
            "literal_copy_loop_address": (
                f"0x{LITERAL_COPY_LOOP_ADDRESS:08X}"
            ),
            "literal_copy_loop_word": f"0x{literal_copy_word:08X}",
        },
        "decoded_font": {
            "pointer_address": f"0x{FONT_POINTER_ADDRESS:08X}",
            "runtime_pointer": f"0x{runtime_pointer:08X}",
            "size_address": f"0x{FONT_SIZE_ADDRESS:08X}",
            "runtime_size": runtime_size,
            "runtime_sha256": runtime_sha256,
            "expected_size": expected_size,
            "expected_sha256": expected_sha256,
        },
        "opening_text": {
            "entry_id": surface.entry_id,
            "runtime_address": f"0x{opening_text_address:08X}",
            "size": len(runtime_opening_text),
            "runtime_sha256": hashlib.sha256(
                runtime_opening_text
            ).hexdigest(),
            "expected_sha256": hashlib.sha256(
                expected_opening_text
            ).hexdigest(),
            "exact": runtime_opening_text == expected_opening_text,
        },
        "checks": checks,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"PCSX2: {version}; {title}; {game_id}")
    print(
        f"decoded font: 0x{runtime_pointer:08X}, "
        f"{runtime_size} bytes, SHA-256 {runtime_sha256}"
    )
    print(f"status: {report['status']}")
    print(f"json: {output}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
