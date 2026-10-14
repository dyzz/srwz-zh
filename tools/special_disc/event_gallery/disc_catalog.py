"""Update SP's VMAP.DAT sector catalog when a member is relocated.

The native resource reader uses this catalog rather than asking ISO9660 for
each archive. Its 48-byte records contain a 40-byte path, LBA and sector count.
"""
import math
import struct


def patch(data, members, changes):
    if len(data) % 48:
        raise ValueError("Unexpected VMAP record size")
    output = bytearray(data)
    seen = set()
    edits = []
    for offset in range(0, len(data), 48):
        if data[offset:offset + 48] == bytes(48):
            if any(data[offset:]):
                raise ValueError("VMAP has records after its terminator")
            break
        raw = data[offset:offset + 40].split(b"\0", 1)[0].decode("ascii")
        path = raw.replace("\\", "/").replace("//", "/").lstrip("/")
        if path.endswith(";1"):
            path = path[:-2]
        if path in seen or path not in members:
            raise ValueError(f"VMAP path preimage changed: {path}")
        seen.add(path)
        lba, count = struct.unpack_from("<II", data, offset + 40)
        member = members[path]
        if (lba, count) != (member.extent_lba, math.ceil(member.size / 2048)):
            raise ValueError(f"VMAP extent preimage changed: {path}")
        if path in changes:
            new_lba, new_size = changes[path]
            new_count = math.ceil(new_size / 2048)
            struct.pack_into("<II", output, offset + 40, new_lba, new_count)
            edits.append({"path": path, "record_offset": offset,
                          "old_lba": lba, "old_sectors": count,
                          "new_lba": new_lba, "new_sectors": new_count})
    if "AID_DATA/AIDDATA.BIN" not in seen:
        raise ValueError("VMAP lacks the relocated AID archive")
    return bytes(output), {"records_checked": len(seen), "edits": edits,
                           "not_catalogued": sorted(set(changes) - seen)}
