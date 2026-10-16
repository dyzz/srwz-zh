"""Native Special Theater event-gallery menu and compact five-banner layout."""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
from srwz.text import encode_text, two_byte_visible_spaces
from special_disc.writeback.migrate_slps_text import encoding_tables

DATA_BASE = 0x820000
CALLBACK_ADDRESS = 0x822000
ELF_ADDRESS_BIAS = 0xFF680
BANNER_CENTRES = {0: 90, 1: 153, 2: 216, 8: 216, 3: 279, 9: 342}


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
    assert items and all(item.get("name") for item in items)
    names = [text(item["name"]) for item in items]
    strings = alloc(struct.pack(f"<{len(names) + 1}I", *names, 0))
    child = alloc(original(0x48A040, 0x120))
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
    assert len(data) < 0x1F00, "Menu overlaps the runtime communication block"
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
                    "gallery_list": {"rows": len(items), "native_row_pitch": min(12, 144 // len(items)), "pages": 1,
                                     "transition": "snap gallery list horizontal offset during drawing"},
                    "extended_help_tables": [hex(x) for x in help_tables]},
    }
    (outdir / "menu-receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    return receipt
