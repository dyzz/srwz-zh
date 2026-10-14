"""Grow AID block 2 in normal archive order; preserve every other chunk.

The caller relocates the expanded AID member and ELF into a candidate ISO. This
module neither edits an ISO nor relocates unrelated disc members.
"""
from __future__ import annotations

import hashlib
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
from srwz.codec import decode_production, reencode_changed_suffix
from .banner import append as append_banner

OFFSET_TABLE = 0x37D510
DECODED_SIZE = 0x37CD08
# Special Theater owns a second AID table copy. Its 321510 loader reads the
# virtual addresses 488ec0/4896d0, rather than the general AID consumer's
# 47c380/47cb90 copy. Keep both coherent after the archive grows.
OFFSET_TABLES = (OFFSET_TABLE, 0x38A050)
DECODED_SIZES = (DECODED_SIZE, 0x389848)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def patch_aid(archive: bytes, elf: bytes) -> tuple[bytes, bytes, dict]:
    """Return expanded archive, table-patched ELF, and byte-preservation receipt."""
    offsets = []
    for i in range(1024):
        value = struct.unpack_from("<I", elf, OFFSET_TABLE + i * 4)[0]
        offsets.append(value)
        if value == len(archive):
            break
    else:
        raise ValueError("AID offset table lacks an archive-size sentinel")
    assert all(a < b for a, b in zip(offsets, offsets[1:]))
    for table in OFFSET_TABLES:
        assert list(struct.unpack_from(f"<{len(offsets)}I", elf, table)) == offsets, "AID duplicate table drift"
    a, b = offsets[2:4]
    decoded = decode_production(archive[a:b]).output
    for size_offset in DECODED_SIZES:
        assert struct.unpack_from("<I", elf, size_offset)[0] == len(decoded)
    updated, banner_receipt = append_banner(decoded)
    encoded = reencode_changed_suffix(archive[a:b], updated, strategy="rust-fit")
    encoded_padded = encoded + bytes((-len(encoded)) % 16)
    delta = len(encoded_padded) - (b - a)
    result = archive[:a] + encoded_padded + archive[b:]
    patched_elf = bytearray(elf)
    edits = []
    for size_offset in DECODED_SIZES:
        struct.pack_into("<I", patched_elf, size_offset, len(updated))
        edits.append({"offset": hex(size_offset), "value": len(updated), "kind": "decoded-size"})
    for table in OFFSET_TABLES:
        for i in range(3, len(offsets)):
            value = offsets[i] + delta
            struct.pack_into("<I", patched_elf, table + 4 * i, value)
            edits.append({"offset": hex(table + 4 * i), "value": value, "kind": "archive-offset"})
    # This stronger check covers padding/trailing bytes as well as the compressed
    # streams. The changed block is the only byte range replaced in the archive.
    assert result[:a] == archive[:a]
    assert result[b + delta:] == archive[b:]
    assert decode_production(result[a:a + len(encoded)]).output == updated
    receipt = {"base_archive_size": len(archive), "archive_size": len(result), "archive_delta": delta,
               "block": 2, "block_start": a, "old_allocation": b - a, "compressed_size": len(encoded),
               "padded_allocation": len(encoded_padded), "all_other_blocks_and_padding_byte_identical": True,
               "base_archive_sha256": sha256(archive), "archive_sha256": sha256(result),
               "base_elf_sha256": sha256(elf), "elf_sha256": sha256(patched_elf),
               "table_entries": len(offsets), "duplicate_offset_tables": [hex(x) for x in OFFSET_TABLES],
               "duplicate_decoded_size_entries": [hex(x) for x in DECODED_SIZES],
               "elf_edits": edits, "banner": banner_receipt,
               "iso_status": "No ISO written. Caller must synchronize ISO/UDF directory metadata and native VMAP.DAT file catalog for relocated members."}
    return result, bytes(patched_elf), receipt

