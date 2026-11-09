"""Install and verify bounded repairs to KVPDATA sprite joins."""

from __future__ import annotations

import json
from pathlib import Path

from .ui_headings import UiHeadingError, checked


CONFIG_PATH = "config/assets/ui-frame-joins.json"


def load_join_contract(root: Path, edition: str) -> dict:
    config = json.loads((root / CONFIG_PATH).read_text())
    if config["schema_version"] != 1 or edition not in ("original", "best", "sp"):
        raise UiHeadingError("unknown frame join contract or edition")
    return config["editions"]["sp" if edition == "sp" else "main"]


def _transform(drawings: bytes, contract: dict, *, reverse: bool) -> tuple[bytes, dict]:
    if len(drawings) != contract["member_size"]:
        raise UiHeadingError("frame join member size drift")
    source_key, target_key = ("after", "before") if reverse else ("before", "after")
    result = bytearray(drawings)
    previous_end = 0
    chunks = {}
    offsets = []
    for chunk in contract["chunks"]:
        index, start, end = chunk["index"], chunk["start"], chunk["end"]
        if index in chunks or not previous_end <= start < end <= len(drawings):
            raise UiHeadingError("frame join chunk overlap or invalid bounds")
        previous_end = end
        label = f"frame join chunk {index}"
        checked(drawings[start:end], {"size": end - start, "sha256": chunk[f"{source_key}_sha256"]}, label)
        previous_offset = -1
        for change in chunk["changes"]:
            offset = change["offset"]
            old, new = change[source_key], change[target_key]
            if not previous_offset < offset < end - start:
                raise UiHeadingError(f"{label} duplicate or out-of-range byte")
            if not 0 <= old <= 255 or not 0 <= new <= 255 or old == new or drawings[start + offset] != old:
                raise UiHeadingError(f"{label} invalid replacement byte or preimage drift")
            previous_offset = offset
            result[start + offset] = new
            offsets.append(start + offset)
        if previous_offset == -1:
            raise UiHeadingError(f"{label} has no changes")
        checked(result[start:end], {"size": end - start, "sha256": chunk[f"{target_key}_sha256"]}, label)
        chunks[str(index)] = chunk["after_sha256"]
    if not chunks:
        raise UiHeadingError("empty frame join contract")
    return bytes(result), {"patched_chunks": chunks, "byte_offsets": offsets, "byte_count": len(offsets)}


def apply_frame_joins(drawings: bytes, contract: dict) -> tuple[bytes, dict]:
    """Repair only the frozen UV and vertex bytes, with whole-chunk checks."""
    return _transform(drawings, contract, reverse=False)


def frame_join_preimage_for_verification(drawings: bytes, contract: dict) -> tuple[bytes, dict]:
    """Check the final joins and reconstruct the exact preceding build pass."""
    return _transform(drawings, contract, reverse=True)
