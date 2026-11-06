"""Native Special Theater event-gallery menu and compact five-banner layout."""
from __future__ import annotations

import json
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
from srwz.text import encode_text, two_byte_visible_spaces
from special_disc.writeback.migrate_slps_text import encoding_tables
from special_disc.event_gallery.ligature import W_CHARACTER, W_CODE, showtime_text

DATA_BASE = 0x820000
CALLBACK_ADDRESS = 0x822000
ELF_ADDRESS_BIAS = 0xFF680
BANNER_CENTRES = {0: 90, 1: 153, 2: 216, 8: 216, 3: 279, 9: 342}
# List rows draw with native font size 5 (0x43D480; table 0x49E190 row 5 =
# 20/9/20/...): Latin, digits and symbols otherwise take whole 20-px cells.
# A run gets glyph width/advance per character, explicit height 9, and the
# native 20/20/9 restore. The full stop's dot sits at the cell's left edge and
# a condensed Σ reads as a thin stroke, so both get their own pair. Long Latin
# author-facing runs use a uniform advance; Showtime gets per-letter metrics
# from showtime_text() when encoded into the gallery menu.
LIST_COMPACT_RUN = re.compile(r"[A-Za-z0-9Σ·.\-]+")
LIST_COMPACT = (0x0E, 0x0C)
LIST_COMPACT_CHAR = {".": (0x0E, 0x07), "Σ": (0x12, 0x10)}
LIST_LONG_RUN, LIST_LONG_SPACE = 5, 0x0A
LIST_FULL_METRICS = "<width:14><space:14><height:09>"


def compact_list_name(name: str) -> str:
    def scope(match):
        run = match[0]
        out, active, active_height = [], None, None
        for character in run:
            width, space = LIST_COMPACT_CHAR.get(character, LIST_COMPACT)
            if len(run) >= LIST_LONG_RUN and character not in LIST_COMPACT_CHAR:
                space = LIST_LONG_SPACE
            if (width, space) != active:
                out.append(("" if active and active[0] == width else f"<width:{width:02X}>")
                           + ("" if active and active[1] == space else f"<space:{space:02X}>"))
                active = (width, space)
            # The gallery glyph hook lowers height-8 digits by one native
            # Y unit, then extends only their packet top by half a unit:
            # effective height 8.5 with the original bottom. Letters use 9.
            height = 0x08 if character.isdigit() else 0x09
            if height != active_height:
                out.append(f"<height:{height:02X}>")
                active_height = height
            out.append(character)
        return "".join(out) + LIST_FULL_METRICS
    formatted = LIST_COMPACT_RUN.sub(scope, name)
    # Every full-width segment has explicit width/advance/height. The initial
    # hanzi segment must not rely on native classification or cached metrics;
    # subsequent segments already receive the compact scope's full restore.
    if name and not LIST_COMPACT_RUN.match(name):
        formatted = LIST_FULL_METRICS + formatted
    return formatted


def build(base_elf: bytes, items: list[dict], outdir: Path, proposal: Path | None = None) -> dict:
    """Write native menu data/ELF patch words and return the build receipt.

    Items are already ordered by the caller and contain name/effects/map. The
    renderer, navigation and page switching remain the SP game's native UI.
    ``proposal`` is the installed-font codebook shared with every SP writer.
    """
    outdir.mkdir(parents=True, exist_ok=True)
    data = bytearray()
    table, _, overrides, _ = encoding_tables(proposal)

    def original(address, size):
        offset = address - ELF_ADDRESS_BIAS
        assert 0 <= offset and offset + size <= len(base_elf)
        return base_elf[offset:offset + size]

    def alloc(payload):
        data.extend(bytes((-len(data)) % 16))
        address = DATA_BASE + len(data)
        data.extend(payload)
        return address

    def setword(address, offset, value):
        struct.pack_into("<I", data, address - DATA_BASE + offset, value & 0xFFFFFFFF)

    def text(value):
        return alloc(encode_text(two_byte_visible_spaces(value), table,
                                 overrides=overrides, terminate=True))

    label = text("名场面集")
    event_help = "重温出击、合体等剧情名场面。播放中按×可返回。"
    help_text = text(event_help)
    # Native ○ / △ button icons; no space between the items, the icon's own
    # margin separates them and the guide ends inside the heading bar.
    list_help = "<-1>只看演出<-3>连同对白"
    assert items and all(item.get("name") for item in items)
    # Keep t and i as ordinary font glyphs; only w has a private raster.
    names = []
    for item in items:
        value = compact_list_name(item["name"])
        local_overrides = overrides
        if item["name"] == "BIG-O·Showtime":
            value = showtime_text()
            local_overrides = dict(overrides, **{W_CHARACTER: W_CODE})
        names.append(alloc(encode_text(two_byte_visible_spaces(value), table,
                                       overrides=local_overrides, terminate=True)))
    strings = alloc(struct.pack(f"<{len(names) + 1}I", *names, 0))
    # The list page is the list widget alone; add a static text widget built
    # from the root page's first help line (id 5) so the entry modes show
    # beside the page heading. Its navigation links stay unset like the list's, and
    # flag bit 0 (hidden; the root page reveals its own help lines) is cleared.
    note = bytearray(original(0x48AD90, 0x90))
    struct.pack_into("<I", note, 8, text(list_help))
    struct.pack_into("<4i", note, 0x60, -1, -1, -1, -1)
    assert struct.unpack_from("<I", note, 0x70)[0] == 0xB
    struct.pack_into("<I", note, 0x70, 0xA)
    struct.pack_into("<2f", note, 0x10, -246, -110)  # right of the "名场面集" heading
    struct.pack_into("<I", note, 0x24, 0)  # no backing band; it would dim the page counter
    child = alloc(original(0x48A040, 0x90) + note + original(0x48A0D0, 0x90))
    setword(child, 12, strings)
    setword(child, 0x78, CALLBACK_ADDRESS)

    root = bytearray(original(0x48AD90, 0x510))

    def size_banner(buffer, offset, ident):
        struct.pack_into("<f", buffer, offset + 0x14, BANNER_CENTRES[ident] - 234)
        struct.pack_into("<I", buffer, offset + 0x1C, 30)
        # Preserve the 620x80 source UV; resize only both destination states.
        struct.pack_into("<f", buffer, offset + 0x44, 60)
        struct.pack_into("<f", buffer, offset + 0x5C, 60)

    for row, ident in ((4, 0), (5, 1), (6, 2), (7, 8), (8, 3)):
        size_banner(root, row * 0x90, ident)
    struct.pack_into("<I", root, 4 * 0x90 + 0x60, 9)
    struct.pack_into("<I", root, 8 * 0x90 + 0x68, 9)
    button = bytearray(original(0x48AD90 + 4 * 0x90, 0x90))
    struct.pack_into("<I", button, 0, 9)
    struct.pack_into("<2I", button, 0x28, 5, 5)
    size_banner(button, 0, 9)
    struct.pack_into("<4I", button, 0x60, 3, 0xFFFFFFFF, 0, 0xFFFFFFFF)
    struct.pack_into("<I", button, 0x70, 0)
    struct.pack_into("<I", button, 0x78, 0x324CF0)
    struct.pack_into("<I", button, 0x80, 6)
    root += button + original(0x48B2A0, 0x90)
    rootptr = alloc(root)
    menu = bytearray(original(0x48B330, 6 * 20))
    struct.pack_into("<I", menu, 8, rootptr)
    menu += struct.pack("<5I", 6, 1, child, 0, label)
    menu += struct.pack("<5I", 0xFFFFFFFF, 0, 0, 0, 0)
    menuptr = alloc(menu)
    # 327090 selects one of two stock native help tables according to unlock
    # state. Extend both tables rather than overriding other entries' help text.
    help_tables = []
    for address in (0x48B3C0, 0x48B420):
        native = original(address, 0x60)
        assert struct.unpack_from("<I", native, 0x50)[0] == 0xFFFFFFFF
        extended = native[:0x50] + struct.pack("<4I", 9, help_text, 0x4B6EF8, 0x4B6EF8) + native[0x50:]
        help_tables.append(alloc(extended))
    # Per-draw record range for the digit optical-height hook. The glyph
    # hook clears it whenever the source leaves this menu pool.
    assert len(data) <= 0x1400, "Menu overlaps the private w glyph"
    data.extend(bytes(0x1C00 - len(data)))
    (outdir / "menu-data.bin").write_bytes(data)

    expected = {0x3277AC: 0x3C050049, 0x3277B8: 0x24A5B330,
                0x3270D4: 0x3C030049, 0x3270D8: 0x2463B420,
                0x3270E8: 0x3C030049, 0x3270EC: 0x2463B3C0}
    patches = [(0x3277AC, 0x3C050000 | (menuptr >> 16)),
               (0x3277B8, 0x34A50000 | (menuptr & 0xFFFF)),
               (0x3270D4, 0x3C030000 | (help_tables[1] >> 16)),
               (0x3270D8, 0x34630000 | (help_tables[1] & 0xFFFF)),
               (0x3270E8, 0x3C030000 | (help_tables[0] >> 16)),
               (0x3270EC, 0x34630000 | (help_tables[0] & 0xFFFF))]
    for address, word in patches:
        assert original(address, 4) == struct.pack("<I", expected[address]), hex(address)
        (outdir / f"patch-{address:x}.bin").write_bytes(struct.pack("<I", word))

    # Standalone callback probe retained for callers that test selection before
    # linking the complete runtime. The linked player occupies CALLBACK_ADDRESS.
    words = [0x10E00006, 0, 0x8CE2004C, 0x3C030082, 0xAC621F00,
             0x24020001, 0xAC621F04, 0x03E00008, 0x00001021]
    (outdir / "menu-callback.bin").write_bytes(struct.pack(f"<{len(words)}I", *words))
    receipt = {
        "data_base": hex(DATA_BASE), "data_size": len(data), "menu": hex(menuptr),
        "child": hex(child), "items": items, "patches": [hex(a) for a, _ in patches],
        "root_ui": {"banner_centres": BANNER_CENTRES, "destination_height": 60,
                    "new_widget": 9, "new_picture": 5, "new_page": 6,
                    "navigation": [0, 1, 2, 3, 9], "wallpaper_widget": 8,
                    "native_heading_and_help_preserved": True,
                    "event_help": event_help,
                    "gallery_list": {"rows": len(items), "paging": "native (left/right)", "help": list_help,
                                     "entry": {"circle": "effects only", "triangle": "with map dialogue"},
                                     "transition": "snap gallery list horizontal offset during drawing"},
                    "extended_help_tables": [hex(x) for x in help_tables]},
    }
    (outdir / "menu-receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    return receipt
