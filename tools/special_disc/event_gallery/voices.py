"""Restore CCC voice clips SP's own effects reference but its disc lacks.

``voice_restorations`` (written by ``author_voices.py``) lists SP CCC ids at or
past the end of SP's ``SOUND/CCC.MSH`` directory, each with an Original clip
asset. The clips are appended to ``SOUND/CCC.MSB`` (grown in place by the
caller) and the directory gains the matching rows and count. The directory is
``size, 0x34, count`` then 8-byte ``size, offset`` rows; the sound driver
indexes it directly (``FUN_0018a9c0``) and rejects ids at or past the count.
"""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path

MSH = "SOUND/CCC.MSH"
MSB = "SOUND/CCC.MSB"
ALIGN = 16  # ADPCM block size; every native clip offset is a multiple of it


def restore_voices(msh: bytes, msb_size: int, restorations, root: Path) -> dict:
    if not restorations:
        return {"msh": msh, "msb_tail": b"", "receipt": {"restored": []}}
    directory = bytearray(msh)
    count = struct.unpack_from("<I", directory, 8)[0]
    if struct.unpack_from("<I", directory, 0)[0] != len(msh):
        raise ValueError("CCC.MSH size word drifted")
    if msb_size % ALIGN:
        raise ValueError("CCC.MSB end is not ADPCM aligned")
    tail, rows = bytearray(), []
    for row in sorted(restorations, key=lambda r: r["sp_ccc"]):
        clip = (Path(root) / row["file"]).read_bytes()
        if len(clip) != row["size"] or hashlib.sha256(clip).hexdigest() != row["sha256"]:
            raise ValueError(f"voice asset drifted: {row['file']}")
        if len(clip) % ALIGN:
            raise ValueError(f"voice asset is not whole ADPCM blocks: {row['file']}")
        index = row["sp_ccc"]
        if index != count:
            raise ValueError(f"CCC {index}: restorations must extend the directory in order (count {count})")
        at = 12 + 8 * index
        if at + 8 > len(directory) or any(directory[at:at + 8]):
            raise ValueError(f"CCC.MSH has no free row for {index}")
        offset = msb_size + len(tail)
        struct.pack_into("<II", directory, at, len(clip), offset)
        tail += clip
        count += 1
        rows.append({"sp_ccc": index, "original_ccc": row["original_ccc"], "size": len(clip),
                     "msb_offset": offset, "sha256": row["sha256"]})
    struct.pack_into("<I", directory, 8, count)
    return {"msh": bytes(directory), "msb_tail": bytes(tail),
            "receipt": {"restored": rows, "msh_count": count, "msb_size_before": msb_size,
                        "msb_size_after": msb_size + len(tail),
                        "msh_sha256": hashlib.sha256(directory).hexdigest()}}


def verify_restored(msh: bytes, msb_tail: bytes, receipt: dict) -> dict:
    count = struct.unpack_from("<I", msh, 8)[0]
    if count != receipt.get("msh_count", count):
        raise AssertionError("CCC.MSH count readback differs")
    for row in receipt["restored"]:
        size, offset = struct.unpack_from("<II", msh, 12 + 8 * row["sp_ccc"])
        start = offset - receipt["msb_size_before"]
        clip = msb_tail[start:start + size]
        if (size, offset) != (row["size"], row["msb_offset"]) or hashlib.sha256(clip).hexdigest() != row["sha256"]:
            raise AssertionError(f"restored CCC {row['sp_ccc']} readback differs")
    return {"restored": [r["sp_ccc"] for r in receipt["restored"]], "verified": True}
