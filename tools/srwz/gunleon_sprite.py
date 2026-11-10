"""Trim the stray atlas row in Gunleon's Chain Decutter animation."""

from contextlib import contextmanager
from hashlib import sha256
import struct
from pathlib import Path
import tempfile

from .codec import decode_production, reencode_changed_suffix
from .iso9660 import member_map, scan_iso9660
from .release_inputs import copy_file, sha256_file


ARCHIVE = "BTL/TWP.BIN"
SEGMENTS = "BTL/TWP.SEG"
CHUNKS = {"original": 616, "best": 616, "sp": 630}
SOURCE_SHA256 = "c33b69316ad5e7713d42e3d8b21c2758821d8427b39009f3b3259c6d3d0cb088"
# Four copies of the same leg keyframe. The black line comes from atlas row 64.
# Advance V and the Y anchor together so the retained rows keep their positions.
KEYFRAMES = (0x12DDA, 0x5BD0E, 0x6FE86, 0x76C92)
BEFORE = struct.pack("<h4H", -36, 56, 72, 64, 64)
AFTER = struct.pack("<h4H", -35, 56, 71, 64, 65)


def repair_animation(source: bytes) -> bytes:
    if sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError("Gunleon animation source hash changed")
    result = bytearray(source)
    for offset in KEYFRAMES:
        if source[offset:offset + len(BEFORE)] != BEFORE:
            raise ValueError(f"Gunleon leg keyframe changed at {offset:#x}")
        result[offset:offset + len(BEFORE)] = AFTER
    return bytes(result)


def animation_slot(iso: Path, edition: str) -> tuple[int, bytes]:
    chunk = CHUNKS[edition]
    members = member_map(scan_iso9660(iso))
    segment, archive = members[SEGMENTS], members[ARCHIVE]
    if (chunk + 2) * 4 > segment.size:
        raise ValueError("Gunleon animation is outside the segment table")
    with iso.open("rb") as stream:
        stream.seek(segment.extent_lba * 2048 + chunk * 4)
        start, end = struct.unpack("<II", stream.read(8))
        if not 0 <= start < end <= archive.size:
            raise ValueError("Gunleon animation has invalid archive bounds")
        offset = archive.extent_lba * 2048 + start
        size = end - start
        stream.seek(offset)
        return offset, stream.read(size)


def verify_fixed_iso(source: Path, output: Path, edition: str, receipt=None) -> dict:
    """Reprove the four keyframes and byte identity outside their packed slot."""
    from special_disc.writeback.build_text_candidate import verify_iso_ranges

    offset, encoded = animation_slot(source, edition)
    output_offset, reread = animation_slot(output, edition)
    if (output.stat().st_size != source.stat().st_size
            or (offset, len(encoded)) != (output_offset, len(reread))
            or member_map(scan_iso9660(output)) != member_map(scan_iso9660(source))):
        raise ValueError("Gunleon repair changed the ISO layout")
    original = decode_production(encoded).output
    fixed = repair_animation(original)
    decoded = decode_production(reread)
    if decoded.output != fixed or any(reread[decoded.consumed:]):
        raise ValueError("Gunleon animation ISO readback differs")
    verification = verify_iso_ranges(source, output, [(offset, offset + len(encoded))])
    result = {
        "member": ARCHIVE,
        "chunk": CHUNKS[edition],
        "keyframe_offsets": list(KEYFRAMES),
        "changed_decoded_bytes": sum(a != b for a, b in zip(original, fixed)),
        "decoded_sha256": sha256(fixed).hexdigest(),
        "allocation_bytes": len(encoded),
        "packed_bytes": decoded.consumed,
        "verification": verification,
    }
    if receipt is not None and result != receipt:
        raise ValueError("Gunleon receipt does not match the ISO and animation input")
    return result


def build_fixed_iso(source: Path, output: Path, edition: str) -> dict:
    """Write a private candidate and verify the fixed allocation and ISO readback."""
    if source.resolve() == output.resolve():
        raise ValueError("Gunleon repair requires a separate output ISO")
    offset, encoded = animation_slot(source, edition)
    size = len(encoded)
    decoded = decode_production(encoded)
    fixed = repair_animation(decoded.output)
    replacement = reencode_changed_suffix(
        encoded, fixed, strategy="rust-patch", max_output_size=size, original_result=decoded,
    )
    payload = replacement.ljust(size, b"\0")
    copy_file(source, output)
    with output.open("r+b") as stream:
        stream.seek(offset)
        stream.write(payload)
        stream.seek(offset)
        if stream.read(size) != payload:
            raise ValueError("Gunleon packed animation ISO readback differs")
    return verify_fixed_iso(source, output, edition)


@contextmanager
def verified_sprite_input(root: Path, target: Path, edition: str, proof: dict, original_slot: bytes):
    """Restore the original packed slot in a temporary clone for earlier verifiers."""
    offset, slot = animation_slot(target, edition)
    if len(slot) != len(original_slot) or target.stat().st_size != proof["input"]["size"]:
        raise ValueError("Gunleon release preimage has the wrong size")
    temporary_root = root / "build/iso/.tmp"
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="release-gunleon-", dir=temporary_root) as directory:
        source = Path(directory) / "pre-gunleon.iso"
        copy_file(target, source)
        with source.open("r+b") as stream:
            stream.seek(offset)
            stream.write(original_slot)
        if sha256_file(source) != proof["input"]["sha256"]:
            raise ValueError("Gunleon release input binding mismatch")
        verify_fixed_iso(source, target, edition, proof["verification"])
        yield source
