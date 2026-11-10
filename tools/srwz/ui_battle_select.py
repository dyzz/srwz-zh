"""Install the reviewed battle SELECT title atlas and edition-specific routes."""
import struct

from .ui_menu_restore import decode, pages, positions, require, sha

CONFIG = "config/assets/ui-battle-select-titles-zh.json"
SP_CONFIG = "config/assets/special-disc/battle-select-titles-zh.json"
SP_SHIP_DRAW_ADDRESS = 0x845B00  # Reserved at the end of the SP gallery load segment.


def apply_atlas(atlas, contract, *, strict=False, reverse=False):
    indices, ranges = pages(atlas, contract)
    owned = {}
    for cell in contract["cells"]:
        page = cell.get("page", contract.get("page"))
        pixels = indices[page]
        occupied = owned.setdefault(page, set())
        pos = positions(cell["rect"])
        tile = decode(cell["indices_zlib_base64"])
        require(len(tile) == len(pos) and max(tile) <= 15 and sha(tile) == cell["sha256"],
                "battle SELECT tile identity drift")
        require(not occupied.intersection(pos), "battle SELECT cells overlap")
        occupied.update(pos)
        before = bytes(len(pos))
        if "before_indices_zlib_base64" in cell:
            before = decode(cell["before_indices_zlib_base64"])
            require(len(before) == len(pos) and max(before) <= 15 and sha(before) == cell["before_sha256"],
                    "battle SELECT tile preimage identity drift")
        current = bytes(pixels[i] for i in pos)
        require(current == tile or (not strict and current == before), "battle SELECT atlas preimage drift")
        for i, value in zip(pos, before if reverse else tile):
            pixels[i] = value
    result = bytearray(atlas)
    for page in owned:
        start, end = ranges[page]
        pixels = indices[page]
        result[start:end] = bytes(a | b << 4 for a, b in zip(pixels[::2], pixels[1::2]))
    return bytes(result)


def write_ranges(contract, edition):
    spec = contract["executables"][edition]
    hook = spec["hook_offset"]
    payloads = (spec, *spec.get("additional_payloads", ()))
    return [(hook, hook + 8)] + [
        (p["payload_offset"], p["payload_offset"] + p["payload_size"]) for p in payloads
    ]


def apply_executable(executable, contract, edition, *, strict=False):
    spec = contract["executables"][edition]
    (hook, hook_end), *ranges = write_ranges(contract, edition)
    start = ranges[0][0]
    if "segment_offset" in spec:
        segment = spec["segment_offset"]
        segment_bytes = bytes.fromhex(spec["segment_hex"])
        require(executable[segment:segment + 32] == segment_bytes,
                f"{edition}: battle SELECT load segment drift")
        _, segment_start, address, _, size, *_ = struct.unpack("<8I", segment_bytes)
        require(all(segment_start <= lo < hi <= segment_start + size for lo, hi in ranges),
                f"{edition}: battle SELECT payload outside load segment")
        if len(ranges) > 1:
            require(edition == "sp" and len(ranges) == 2
                    and ranges[1][0] == segment_start + SP_SHIP_DRAW_ADDRESS - address,
                    f"{edition}: battle SELECT ship drawing slot drift")
    else:
        require(len(ranges) == 1, f"{edition}: battle SELECT additional payload needs a load segment")
    before = bytes.fromhex(spec["before_hex"])
    after = bytes.fromhex(spec["after_hex"])
    require(0 <= hook < hook_end + 4 <= start and hook % 4 == 0
            and len(before) == len(after) == 12 and before[8:] == after[8:],
            f"{edition}: battle SELECT executable bounds drift")
    writes = [(hook, hook_end + 4, before, after)]
    for (lo, hi), payload_spec in zip(ranges, (spec, *spec.get("additional_payloads", ()))):
        require(writes[-1][1] <= lo < hi <= len(executable) and lo % 4 == hi % 4 == 0,
                f"{edition}: battle SELECT payload bounds or overlap")
        payload = decode(payload_spec["payload_zlib_base64"])
        require(len(payload) == hi - lo and sha(payload) == payload_spec["payload_sha256"],
                f"{edition}: battle SELECT overlay identity drift")
        writes.append((lo, hi, bytes(hi - lo), payload))
    current = tuple(executable[lo:hi] for lo, hi, _, _ in writes)
    require(current == tuple(new for _, _, _, new in writes)
            or (not strict and current == tuple(old for _, _, old, _ in writes)),
            f"{edition}: battle SELECT hook or overlay preimage drift")
    result = bytearray(executable)
    for lo, hi, _, new in writes:
        result[lo:hi] = new
    return bytes(result)
