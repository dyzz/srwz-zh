"""Relocate two SP experiment members in its UDF 1.02 bridge filesystem.

The caller writes member payloads and updates ISO9660 directory records first.
This module updates UDF File Entries, both Partition Descriptors, the Logical
Volume Integrity Descriptor, and anchors. It accepts only this disc's one
physical partition and single short-allocation-descriptor regular files.
No original disc or production output is selected implicitly.
"""
from __future__ import annotations

import argparse
import binascii
import json
import math
import os
from pathlib import Path
import struct

BLOCK = 2048
ALLOWED = {"SLPS_259.20", "AID_DATA/AIDDATA.BIN", "EFF/VEFF2DX.BIN",
           # Restored gallery voices: CCC.MSB grows in place into the extent
           # KVMDATA.BIN vacates by moving to the image tail.
           "KURODATA/KVMDATA.BIN", "SOUND/CCC.MSB"}
# Retail SP already stores this >1 GiB size literally in one short AD; a grown
# copy keeps that layout (still below 4 GiB, same LBA).
OVERSIZE_IN_PLACE = {"SOUND/CCC.MSB"}


def u16(data, offset):
    return struct.unpack_from("<H", data, offset)[0]


def u32(data, offset):
    return struct.unpack_from("<I", data, offset)[0]


def crc_tag(data, location=None):
    """Refresh ECMA-167 descriptor CRC and descriptor-tag checksum."""
    data = bytearray(data)
    length = u16(data, 10)
    if length > len(data) - 16:
        raise ValueError("descriptor CRC span exceeds supplied descriptor")
    if location is not None:
        struct.pack_into("<I", data, 12, location)
    struct.pack_into("<H", data, 8, binascii.crc_hqx(data[16:16 + length], 0))
    data[4] = sum(data[i] for i in range(16) if i != 4) & 255
    return bytes(data)


def validate_tag(data, expected=None):
    tag = u16(data, 0)
    if expected is not None and tag != expected:
        raise ValueError(f"expected UDF descriptor {expected}, found {tag}")
    if data[4] != sum(data[i] for i in range(16) if i != 4) & 255:
        raise ValueError("UDF descriptor tag checksum mismatch")
    length = u16(data, 10)
    if length > len(data) - 16:
        raise ValueError("UDF descriptor CRC span leaves block")
    if u16(data, 8) != binascii.crc_hqx(data[16:16 + length], 0):
        raise ValueError("UDF descriptor CRC mismatch")
    return tag


class Disc:
    def __init__(self, stream):
        self.stream = stream
        self.anchor = self.read(256)
        validate_tag(self.anchor, 2)
        self.sequences = []
        for field in (16, 24):
            length, lba = struct.unpack_from("<II", self.anchor, field)
            descriptors = []
            for s in range(lba, lba + math.ceil(length / BLOCK)):
                b = self.read(s)
                kind = validate_tag(b)
                descriptors.append((s, kind, b))
                if kind == 8:
                    break
            self.sequences.append(descriptors)
        main = self.sequences[0]
        pd = next(b for _, kind, b in main if kind == 5)
        lvd = next(b for _, kind, b in main if kind == 6)
        if u16(pd, 22) != 0 or u32(lvd, 212) != BLOCK:
            raise ValueError("not the SP physical partition profile")
        if struct.unpack_from("<II", lvd, 264) != (6, 1) or lvd[440:446] != bytes.fromhex("010601000000"):
            raise ValueError("unsupported UDF partition mapping")
        self.partition_start, self.partition_length = struct.unpack_from("<II", pd, 188)
        if self.partition_start != 274:
            raise ValueError("SP partition start drift")
        fsd_lba, fsd_part = u32(lvd, 252), u16(lvd, 256)
        if fsd_part != 0:
            raise ValueError("unsupported file-set partition")
        fsd = self.read(self.partition_start + fsd_lba)
        validate_tag(fsd, 256)
        self.integrity_lba = u32(lvd, 436)
        self.integrity = self.read(self.integrity_lba)
        validate_tag(self.integrity, 9)
        if u32(self.integrity, 72) != 1:
            raise ValueError("unsupported integrity partition count")
        self.files = {}
        self.metadata_blocks = {256, self.integrity_lba}
        self.walk(u32(fsd, 404), "", set())

    def read(self, lba, length=BLOCK):
        self.stream.seek(lba * BLOCK)
        data = self.stream.read(length)
        if len(data) != length:
            raise ValueError(f"short image read at LBA {lba}")
        return data

    def walk(self, icb, path, visited):
        if icb in visited:
            raise ValueError("UDF directory/ICB cycle")
        visited.add(icb)
        lba = self.partition_start + icb
        fe = self.read(lba)
        validate_tag(fe, 261)
        self.metadata_blocks.add(lba)
        if (u16(fe, 34) & 7) != 0:
            raise ValueError("only short UDF allocation descriptors supported")
        ea_length, ad_length = struct.unpack_from("<II", fe, 168)
        ad_offset = 176 + ea_length
        if ad_length != 8 or ad_offset + 8 > BLOCK:
            raise ValueError("only one UDF extent per file supported")
        extent_length, extent_block = struct.unpack_from("<II", fe, ad_offset)
        info_length = struct.unpack_from("<Q", fe, 56)[0]
        # Retail SP stores the >1 GiB SOUND/ccc.MSB size literally in its
        # short AD, overlapping standard extent-type bits. Preserve that
        # source quirk for unchanged files; relocated targets stay <1 GiB.
        if extent_length != info_length:
            raise ValueError("UDF information/extent length mismatch")
        record = dict(path=path, fe_lba=lba, fe=fe, ad_offset=ad_offset,
                      extent_lba=self.partition_start + extent_block, size=info_length)
        if fe[27] != 4:
            if fe[27] != 5:
                raise ValueError("unsupported UDF ICB file type")
            self.files[path.upper()] = record
            return
        directory = self.read(record["extent_lba"], info_length)
        self.metadata_blocks.update(range(record["extent_lba"], record["extent_lba"] + math.ceil(info_length / BLOCK)))
        p = 0
        while p < len(directory):
            if not any(directory[p:]):
                break
            if p + 38 > len(directory):
                raise ValueError("truncated UDF file identifier")
            name_length = directory[p + 19]
            impl_length = u16(directory, p + 36)
            length = (38 + impl_length + name_length + 3) & ~3
            fid = directory[p:p + length]
            validate_tag(fid, 257)
            characteristics = fid[18]
            if not characteristics & (4 | 8):
                encoded = fid[38 + impl_length:38 + impl_length + name_length]
                if not encoded:
                    raise ValueError("empty UDF filename")
                if encoded[0] == 8:
                    name = encoded[1:].decode("latin1")
                elif encoded[0] == 16:
                    name = encoded[1:].decode("utf-16-be")
                else:
                    raise ValueError("unsupported UDF compressed Unicode")
                if u16(fid, 28) != 0:
                    raise ValueError("unexpected ICB partition")
                self.walk(u32(fid, 24), f"{path}/{name}".strip("/"), visited)
            p += length


def relocate(imagePath, changes, *, allowed_members=None):
    """Update candidate UDF metadata for {path: (absolute_lba, byte_size)}.

    Returns an auditable receipt. If files leave the old partition, the image
    gains a 257-sector metadata tail: reserve anchor, 255 zero blocks, final
    anchor. ISO9660 Volume Space Size is also refreshed because the caller's
    earlier directory update may have preceded this final metadata extension.
    """
    path = Path(imagePath)
    normalized = {name.upper().strip("/"): tuple(map(int, value)) for name, value in changes.items()}
    allowed = ALLOWED if allowed_members is None else frozenset(allowed_members)
    if allowed not in (ALLOWED, {"SLPS_258.87", "EFF/VEFF2DX.BIN"},
                       {"SLPS_732.70", "EFF/VEFF2DX.BIN"}):
        raise ValueError("unknown subtitle relocation profile")
    if not normalized or not set(normalized) <= allowed:
        raise ValueError("only the gallery ELF, AID and subtitled VEFF members may relocate")
    if path.resolve().parent.name == "rom" or path.name in {"srwz-zh-current.iso", "srwz-sp-zh-current.iso"}:
        raise ValueError("refuses source/production ISO; supply an isolated candidate")
    with path.open("r+b") as f:
        disc = Disc(f)
        original_bytes = os.fstat(f.fileno()).st_size
        if original_bytes % BLOCK:
            raise ValueError("candidate image is not sector-aligned")
        total_blocks = original_bytes // BLOCK
        old_partition_end = disc.partition_start + disc.partition_length
        spans = []
        for name, (lba, size) in normalized.items():
            limit = 1 << 30
            if name in OVERSIZE_IN_PLACE and name in disc.files and lba == disc.files[name]["extent_lba"] \
                    and disc.files[name]["size"] >= limit:
                limit = 1 << 32
            if name not in disc.files or lba < disc.partition_start or not 0 < size < limit:
                raise ValueError(f"invalid SP relocation: {name}")
            end = lba + math.ceil(size / BLOCK)
            if end > total_blocks:
                raise ValueError("member payload has not yet been written into the candidate image")
            for other, record in disc.files.items():
                if other in normalized:
                    continue
                a = record["extent_lba"]; b = a + math.ceil(record["size"] / BLOCK)
                if max(a, lba) < min(b, end):
                    raise ValueError(f"relocation overlaps unchanged member {other}")
            if any(lba <= s < end for s in disc.metadata_blocks):
                raise ValueError("relocation overlaps existing UDF metadata")
            if any(max(a, lba) < min(b, end) for a, b in spans):
                raise ValueError("relocated members overlap")
            spans.append((lba, end))
        new_file_end = max(b for _, b in spans)
        # Appending metadata after the complete caller-written image avoids
        # overwriting either appended payload with the required trailing anchors.
        extended = new_file_end > old_partition_end
        new_partition_length = disc.partition_length
        anchors = [256]
        writes = {}
        if extended:
            tail_start = total_blocks
            final_anchor_lba = tail_start + 256
            total_blocks = final_anchor_lba + 1
            new_partition_length = final_anchor_lba - disc.partition_start
            anchors.extend([tail_start, final_anchor_lba])
            for sequence in disc.sequences:
                for lba, kind, data in sequence:
                    if kind == 5:
                        data = bytearray(data)
                        struct.pack_into("<I", data, 192, new_partition_length)
                        writes[lba] = crc_tag(data)
            integrity = bytearray(disc.integrity)
            # One partition: free-space table at 80; size table at 84.
            # The source's read-only free-space value is zero; preserve it.
            struct.pack_into("<I", integrity, 84, new_partition_length)
            writes[disc.integrity_lba] = crc_tag(integrity)
            for lba in anchors[1:]:
                writes[lba] = crc_tag(disc.anchor, location=lba)
        rows = []
        for name, (lba, size) in normalized.items():
            record = disc.files[name]
            fe = bytearray(record["fe"])
            struct.pack_into("<Q", fe, 56, size)
            struct.pack_into("<Q", fe, 64, math.ceil(size / BLOCK))
            struct.pack_into("<II", fe, record["ad_offset"], size, lba - disc.partition_start)
            writes[record["fe_lba"]] = crc_tag(fe)
            rows.append(dict(path=name, fe_lba=record["fe_lba"], ad_offset=record["ad_offset"],
                             previous_lba=record["extent_lba"], previous_size=record["size"],
                             new_lba=lba, new_size=size))
        # All validation above precedes mutations.
        if extended:
            f.truncate(total_blocks * BLOCK)
        for lba, data in sorted(writes.items()):
            f.seek(lba * BLOCK); f.write(data)
        if extended:
            for lba in range(16, 32):
                data = bytearray(disc.read(lba))
                if data[1:6] == b"CD001" and data[0] in (1, 2):
                    struct.pack_into("<I", data, 80, total_blocks)
                    struct.pack_into(">I", data, 84, total_blocks)
                    f.seek(lba * BLOCK); f.write(data)
        f.flush()
        check = Disc(f)
        for name, (lba, size) in normalized.items():
            if (check.files[name]["extent_lba"], check.files[name]["size"]) != (lba, size):
                raise AssertionError("UDF relocation readback failed")
        for name, record in disc.files.items():
            if name not in normalized:
                if (check.files[name]["extent_lba"], check.files[name]["size"]) != (record["extent_lba"], record["size"]):
                    raise AssertionError("unchanged UDF member moved")
        for lba in anchors[1:]:
            validate_tag(disc.read(lba), 2)
        return dict(image=str(path), partition_start=disc.partition_start,
                    previous_partition_length=disc.partition_length,
                    partition_length=new_partition_length, partition_extended=extended,
                    image_blocks=total_blocks, anchors_written=anchors[1:], files=rows,
                    metadata_blocks_written=sorted(writes),
                    unchanged_members_preserved=len(disc.files) - len(normalized))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    parser.add_argument("changes_json", help='JSON path mapping member names to [absolute_lba, byte_size]')
    args = parser.parse_args()
    print(json.dumps(relocate(args.image, json.loads(Path(args.changes_json).read_text())), indent=2))
