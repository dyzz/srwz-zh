"""Bounded UV repair for the shared nine-slice help frame in KVPDATA.

The left caps are 24 screen pixels wide. With endpoint U1=24 the final
screen pixel samples the transparent atlas column U=23 in installed GS
renderers. End at U1=23 to keep that pixel on the filled column U=22.
Keep the screen vertices and V unchanged.
The mirrored right caps have a different endpoint phase and remain untouched.
"""

from __future__ import annotations

from pathlib import Path
import json

from .ui_headings import UiHeadingError, checked, lock


def load_frame_uv_contract(root: Path, edition: str = "original") -> dict:
    if edition in ("original", "best"):
        path = root / "config/assets/ui-headings-zh.json"
        return json.loads(path.read_text())["shared_frame_uv"]
    if edition == "sp":
        return json.loads((root / "config/assets/special-disc/shared-frame-uv.json").read_text())
    raise UiHeadingError(f"unknown frame UV edition: {edition}")


def verify_frame_uv_patches(drawings: bytes, contract: dict) -> dict:
    """Check the entire repaired chunk, including untouched mirrors and layers."""
    if len(drawings) != contract["member_size"]:
        raise UiHeadingError("frame UV member size drift")
    chunk = contract["chunk"]
    start, end = chunk["start"], chunk["end"]
    if not 0 <= start < end <= len(drawings):
        raise UiHeadingError("frame UV chunk bounds")
    checked(drawings[start:end], {"size": chunk["size"], "sha256": chunk["output_sha256"]},
            "frame UV patched chunk")
    for patch in contract["patches"]:
        offset = patch["offset"]
        if drawings[offset:offset + 22] != bytes.fromhex(patch["after_hex"]):
            raise UiHeadingError("frame UV patched sprite drift")
    return {"style_id": contract["style_id"], "chunk_index": chunk["index"],
            "byte_offsets": sorted(p["offset"] + 20 for p in contract["patches"]),
            "byte_count": len(contract["patches"]),
            "patched_chunk_sha256": lock(drawings[start:end])["sha256"]}


def apply_frame_uv_patches(drawings: bytes, contract: dict) -> tuple[bytes, dict]:
    """Apply one locked shared-style repair; reject drift or wider edits."""
    if len(drawings) != contract["member_size"]:
        raise UiHeadingError("frame UV member size drift")
    chunk = contract["chunk"]
    start, end = chunk["start"], chunk["end"]
    if not 0 <= start < end <= len(drawings):
        raise UiHeadingError("frame UV chunk bounds")
    checked(drawings[start:end], chunk, "frame UV chunk preimage")
    patches = contract["patches"]
    if len(patches) != 9:
        raise UiHeadingError("frame UV repair must cover three left pieces in three layers")
    result = bytearray(drawings)
    claimed = set()
    pieces = set()
    for patch in patches:
        offset = patch["offset"]
        before = bytes.fromhex(patch["before_hex"])
        after = bytes.fromhex(patch["after_hex"])
        if not start <= offset <= end - 22 or len(before) != 22 or len(after) != 22:
            raise UiHeadingError("frame UV sprite bounds")
        positions = set(range(offset, offset + 22))
        if positions & claimed:
            raise UiHeadingError("frame UV ownership overlaps")
        claimed.update(positions)
        if drawings[offset:offset + 22] != before:
            raise UiHeadingError("frame UV sprite preimage drift")
        # Permit only the non-mirrored U1 endpoint repair. Flags, XY, color,
        # palette, material, U0 and both V values must remain byte-exact.
        if (before[0] & 15 != 5 or before[4] != 0x11
                or before[18] != 0 or before[20] != 24
                or after != before[:20] + b"\x17" + before[21:]):
            raise UiHeadingError("frame UV edit exceeds the U1-only contract")
        pieces.add((before[5], before[19], before[21]))
        result[offset:offset + 22] = after
    expected_pieces = {(bank, v0, v1) for bank in (7, 10, 15)
                       for v0, v1 in ((192, 208), (210, 211), (208, 232))}
    if pieces != expected_pieces:
        raise UiHeadingError("frame UV layer or piece coverage drift")
    output = bytes(result)
    allowed = {p["offset"] + 20 for p in patches}
    changed = {i for i, (a, b) in enumerate(zip(drawings, output)) if a != b}
    if changed != allowed:
        raise UiHeadingError("frame UV non-target bytes changed")
    verification = verify_frame_uv_patches(output, contract)
    return output, {**verification,
                    "scope": "all references to the shared style",
                    "input": lock(drawings), "output": lock(output),
                    "runtime": "see external ISO and renderer evidence"}


def frame_uv_preimage_for_verification(drawings: bytes, contract: dict) -> bytes:
    """Verify final UVs, then reconstruct the preceding menu pass on a copy."""
    verify_frame_uv_patches(drawings, contract)
    result = bytearray(drawings)
    for patch in contract["patches"]:
        result[patch["offset"] + 20] = bytes.fromhex(patch["before_hex"])[20]
    chunk = contract["chunk"]
    checked(result[chunk["start"]:chunk["end"]], chunk, "frame UV reconstructed preimage")
    return bytes(result)
