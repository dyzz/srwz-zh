"""Append grown SP members to an ISO9660/UDF image and account for every byte touched.

Members that outgrow their original allocation (the gallery executable, AID
archive and subtitled effect archive) are written after the last sector of the
image. The ISO9660 directory record, both volume descriptors, the native
``VMAP.DAT`` sector catalog and the UDF file entries are then pointed at the
new extents. ``verify_relocation`` re-reads the image and proves that nothing
outside the declared spans changed and that the appended tail holds exactly
the member payloads plus the UDF metadata tail.
"""
from __future__ import annotations

import hashlib
import math
import struct
from pathlib import Path

from srwz.file_identity import remember_digest
from srwz.iso9660 import member_map, scan_iso9660
from special_disc.event_gallery.disc_catalog import patch as patch_catalog
from special_disc.event_gallery.udf import relocate as relocate_udf

SECTOR = 2048
CATALOG = "VMAP.DAT"


def _pad(data: bytes) -> bytes:
    return data + bytes((-len(data)) % SECTOR)


def merge_spans(spans) -> list[tuple[int, int]]:
    """Sorted, non-overlapping half-open byte ranges."""
    merged: list[list[int]] = []
    for start, end in sorted((int(a), int(b)) for a, b in spans if b > a):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(a, b) for a, b in merged]


def patch_catalog_tolerant(data: bytes, before: dict, changes: dict) -> tuple[bytes, dict]:
    """Repoint relocated members in a catalog that already carries inherited
    non-target differences (the main editions' production images moved
    COMPDATA/MTV_PROS without updating the catalog). Target rows must still
    match the directory exactly; other rows are preserved and reported."""
    if len(data) % 48:
        raise ValueError("Invalid native file catalog")
    result = bytearray(data)
    seen, edits, inherited = set(), [], []
    for off in range(0, len(data), 48):
        row = data[off:off + 48]
        if row == bytes(48):
            if any(data[off:]):
                raise ValueError("Catalog data after terminator")
            break
        name = (row[:40].split(b"\0", 1)[0].decode("ascii").replace("\\", "/")
                .replace("//", "/").lstrip("/").removesuffix(";1"))
        if name in seen or name not in before:
            raise ValueError("Unknown or duplicate native file catalog entry")
        seen.add(name)
        lba, count = struct.unpack_from("<II", row, 40)
        member = before[name]
        expected = (member.extent_lba, math.ceil(member.size / SECTOR))
        if (lba, count) != expected:
            if name in changes:
                raise ValueError(f"Relocated catalog preimage mismatch: {name}")
            inherited.append({"member": name, "catalog": [lba, count], "input_directory": list(expected),
                              "preserved_unchanged": True})
        if name in changes:
            new_lba, new_size = changes[name]
            new_count = math.ceil(new_size / SECTOR)
            struct.pack_into("<II", result, off + 40, new_lba, new_count)
            edits.append({"path": name, "record_offset": off, "old_lba": lba, "old_sectors": count,
                          "new_lba": new_lba, "new_sectors": new_count})
    if "EFF/VEFF2DX.BIN" not in seen:
        raise ValueError("Missing effect archive catalog entry")
    return bytes(result), {"records_checked": len(seen), "edits": edits,
                           "inherited_non_target_catalog_differences": inherited,
                           "not_catalogued": sorted(set(changes) - seen)}


CATALOG_POLICIES = {"strict": patch_catalog, "inherit": patch_catalog_tolerant}


def append_members(image: Path, before: dict, members: dict[str, bytes], *, allowed_udf=None,
                   catalog_policy: str = "strict") -> dict:
    """Write ``members`` after the image end and repoint every catalog at them.

    ``before`` is the ISO9660 member map of the image prior to this call. The
    returned receipt lists the new extents and, as ``touched_spans``, each byte
    range inside the original image size that this function rewrote.
    ``catalog_policy`` is ``strict`` (every catalog row must match the
    directory) or ``inherit`` (keep pre-existing non-target differences).
    """
    patch_rows = CATALOG_POLICIES[catalog_policy]
    image = Path(image)
    if not members:
        raise ValueError("no members to relocate")
    for name in members:
        if name not in before:
            raise ValueError(f"unknown member to relocate: {name}")
    old_size = image.stat().st_size
    if old_size % SECTOR:
        raise ValueError("image is not sector aligned")
    changes: dict[str, tuple[int, int]] = {}
    touched: list[tuple[int, int]] = []
    appended = bytearray()
    with image.open("r+b") as stream:
        for name, data in members.items():
            stream.seek(0, 2)
            stream.write(bytes((-stream.tell()) % SECTOR))
            lba = stream.tell() // SECTOR
            stream.write(_pad(data))
            appended += _pad(data)
            changes[name] = (lba, len(data))
            record = before[name].directory_record_offset
            stream.seek(record + 2)
            stream.write(struct.pack("<I", lba) + struct.pack(">I", lba))
            stream.seek(record + 10)
            stream.write(struct.pack("<I", len(data)) + struct.pack(">I", len(data)))
            touched.append((record + 2, record + 18))
        stream.seek(0, 2)
        sectors = stream.tell() // SECTOR
        for descriptor in (16, 17):
            stream.seek(descriptor * SECTOR + 80)
            stream.write(struct.pack("<I", sectors) + struct.pack(">I", sectors))
            touched.append((descriptor * SECTOR + 80, descriptor * SECTOR + 88))
    with image.open("rb") as stream:
        catalog_member = before[CATALOG]
        stream.seek(catalog_member.extent_lba * SECTOR)
        catalog_before = stream.read(catalog_member.size)
    catalog, catalog_receipt = patch_rows(catalog_before, before, changes)
    with image.open("r+b") as stream:
        stream.seek(catalog_member.extent_lba * SECTOR)
        stream.write(catalog)
    touched.append((catalog_member.extent_lba * SECTOR, catalog_member.extent_lba * SECTOR + len(catalog)))
    udf = relocate_udf(image, changes, allowed_members=allowed_udf)
    for lba in udf["metadata_blocks_written"]:
        if lba * SECTOR < old_size:
            touched.append((lba * SECTOR, (lba + 1) * SECTOR))
    # The UDF relocator refreshes the ISO9660 volume space size after extending
    # the image; both descriptor words are already in the touched list.
    return {
        "changes": {name: list(value) for name, value in changes.items()},
        "old_size": old_size, "new_size": image.stat().st_size,
        "appended_sha256": hashlib.sha256(bytes(appended)).hexdigest(),
        "appended_bytes": len(appended),
        "touched_spans": merge_spans(touched),
        "catalog": {"member": CATALOG, "policy": catalog_policy,
                    "sha256": hashlib.sha256(catalog).hexdigest(), **catalog_receipt},
        "udf": udf,
    }


def verify_relocation(image: Path, before: dict, members: dict[str, bytes], receipt: dict) -> dict:
    """Re-read the image: unchanged members keep their extents, relocated members
    and the catalog read back exactly, and the tail is payloads plus UDF metadata."""
    image = Path(image)
    after = member_map(scan_iso9660(image))
    for name, member in before.items():
        if name not in members and after[name] != member:
            raise AssertionError(f"unrelated ISO member moved: {name}")
    with image.open("rb") as stream:
        for name, data in members.items():
            member = after[name]
            if (member.extent_lba, member.size) != tuple(receipt["changes"][name]):
                raise AssertionError(f"relocated member extent drift: {name}")
            stream.seek(member.extent_lba * SECTOR)
            if stream.read(member.size) != data:
                raise AssertionError(f"ISO readback differs: {name}")
        catalog = before[CATALOG]
        stream.seek(catalog.extent_lba * SECTOR)
        on_disk = stream.read(catalog.size)
        if hashlib.sha256(on_disk).hexdigest() != receipt["catalog"]["sha256"]:
            raise AssertionError("native file catalog readback differs")
        for edit in receipt["catalog"]["edits"]:
            if struct.unpack_from("<II", on_disk, edit["record_offset"] + 40) != (edit["new_lba"], edit["new_sectors"]):
                raise AssertionError("native file catalog edit readback differs")
        stream.seek(receipt["old_size"])
        tail = stream.read()
    expected = b"".join(_pad(data) for data in members.values())
    if tail[:len(expected)] != expected or hashlib.sha256(expected).hexdigest() != receipt["appended_sha256"]:
        raise AssertionError("appended member payload differs")
    remainder = tail[len(expected):]
    udf = receipt["udf"]
    if udf["partition_extended"]:
        if len(remainder) != 257 * SECTOR:
            raise AssertionError("unexpected UDF metadata tail length")
        tail_start = receipt["old_size"] // SECTOR + len(expected) // SECTOR
        anchors = {lba - tail_start for lba in udf["anchors_written"] if lba >= tail_start}
        for index in range(257):
            block = remainder[index * SECTOR:(index + 1) * SECTOR]
            if index not in anchors and any(block):
                raise AssertionError("UDF metadata tail holds unexpected data")
    elif remainder:
        raise AssertionError("unexpected bytes after relocated members")
    return {"unchanged_members": len(before) - len(members), "relocated_members": sorted(members),
            "tail_bytes": len(tail), "verified": True}


def verify_untouched(base: Path, final: Path, spans) -> dict:
    """Prove every byte of ``base`` outside ``spans`` is unchanged in ``final``.

    ``final`` is read once end to end, so the pass also yields ``final_sha256``
    (kept in the file-identity store) and the later receipt hash is free.
    """
    base, final = Path(base), Path(final)
    size = base.stat().st_size
    merged = merge_spans(spans)
    if final.stat().st_size < size or any(b > size for _, b in merged):
        raise AssertionError("relocated image is shorter than its base or spans exceed it")
    digest, whole, count = hashlib.sha256(), hashlib.sha256(), 0
    block = 4 * 1024 * 1024
    edges = [(0, 0), *merged, (size, size)]
    with base.open("rb") as left, final.open("rb") as right:
        for (_, start), (end, _) in zip(edges, edges[1:]):
            remaining = start - right.tell()
            while remaining > 0:
                b = right.read(min(block, remaining))
                if not b:
                    raise AssertionError("relocated image ended inside an owned span")
                remaining -= len(b); whole.update(b)
            left.seek(start)
            remaining = end - start
            while remaining:
                a = left.read(min(block, remaining)); b = right.read(len(a))
                if not a or a != b:
                    raise AssertionError(f"unowned ISO range changed at {left.tell() - len(a):X}")
                remaining -= len(a); count += len(a); digest.update(a); whole.update(b)
        while True:
            b = right.read(block)
            if not b:
                break
            whole.update(b)
    final_sha256 = whole.hexdigest()
    remember_digest(final, final_sha256, settled=True)
    return {"base_bytes": size, "compared_bytes": count, "sha256": digest.hexdigest(), "spans": merged,
            "final_sha256": final_sha256}
