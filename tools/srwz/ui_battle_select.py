"""Install the reviewed battle SELECT title atlas and edition-specific routes."""
import json

from .ui_menu_restore import decode, pages, positions, require, sha

CONFIG = "config/assets/ui-battle-select-titles-zh.json"


def apply_atlas(atlas, contract, *, strict=False):
    page = contract["page"]
    indices, ranges = pages(atlas, contract)
    pixels = indices[page]
    owned = set()
    for cell in contract["cells"]:
        pos = positions(cell["rect"])
        tile = decode(cell["indices_zlib_base64"])
        require(len(tile) == len(pos) and max(tile) <= 15 and sha(tile) == cell["sha256"],
                "battle SELECT tile identity drift")
        require(not owned.intersection(pos), "battle SELECT cells overlap")
        owned.update(pos)
        current = bytes(pixels[i] for i in pos)
        require(current == tile or (not strict and not any(current)), "battle SELECT atlas preimage drift")
        for i, value in zip(pos, tile):
            pixels[i] = value
    start, end = ranges[page]
    return atlas[:start] + bytes(a | b << 4 for a, b in zip(pixels[::2], pixels[1::2])) + atlas[end:]


def write_ranges(contract, edition):
    spec = contract["executables"][edition]
    hook, payload = spec["hook_offset"], spec["payload_offset"]
    return [(hook, hook + 8), (payload, payload + spec["payload_size"])]


def apply_executable(executable, contract, edition, *, strict=False):
    spec = contract["executables"][edition]
    (hook, hook_end), (start, end) = write_ranges(contract, edition)
    before = bytes.fromhex(spec["before_hex"])
    after = bytes.fromhex(spec["after_hex"])
    payload = decode(spec["payload_zlib_base64"])
    require(0 <= hook < hook_end + 4 <= start < end <= len(executable)
            and all(offset % 4 == 0 for offset in (hook, start, end))
            and len(before) == len(after) == 12 and before[8:] == after[8:],
            f"{edition}: battle SELECT executable bounds drift")
    require(len(payload) == end - start and sha(payload) == spec["payload_sha256"],
            f"{edition}: battle SELECT overlay identity drift")
    current = (executable[hook:hook_end + 4], executable[start:end])
    applied = (after, payload)
    require(current == applied or (not strict and current == (before, bytes(end - start))),
            f"{edition}: battle SELECT hook or overlay preimage drift")
    return executable[:hook] + after + executable[hook_end + 4:start] + payload + executable[end:]
