"""Read-only layout of a decoded MAPMODEL map member.

``MAP/MAPMODEL.BIN`` member 0 holds shared objects loaded once (``FUN_00180b00``);
battle map n is member n + 1 (``FUN_00143cf0`` loads member ``*0x524b00 + 1``, the
map id a STAGE entry writes); members 81..195 are world-map title pictures (see
``docs/MAPMODEL_WORLD_MAP_TITLES.md``).  A decoded map member is:

* a header of ``u32`` words: section count, header size, 0, then one
  (size, end offset) pair per section, the ends accumulating from 0;
* in section 0, right after the pairs, the map width and height followed by one
  ``u16`` per tile, row by row: low byte a signed height, high byte the index of
  the tile's terrain record (``FUN_00143cf0`` takes the terrain attribute from
  record + 0x18);
* section 1: terrain-name records (0x1C bytes, see ``terrain_names.py``);
* sections 2..: one model each.  A model starts with a transform header (floats:
  scale, rotation, position) and then a Sony HiG plugin directory, a ``u32``
  count followed by 16-byte entries ``name[8], u32 0, u32 offset`` (Frame, Micro,
  Shape, Hrchy, Tex2d, then Anime and Share on animated models).

Every model is a stage object: script opcode ``0x46 m,...`` and the entry
initialisers ``0x146280`` / ``0x146160`` address the member's models in order as
m = 0, 1, ...  (at run time slot 1 + m of the object array; the runtime object
count equals the member's model count).  The first model is usually the large
static mesh; animated parts carry an ``Anime`` plugin.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

MEMBER_TABLE_OFFSET = 0x2FAAD0  # SLPS_258.87 file offset of the 197 member offsets
MEMBER_COUNT = 196
MAP_MEMBERS = range(0, 81)


@dataclass
class MapModel:
    index: int
    start: int
    end: int
    plugins: list[tuple[str, int]] = field(default_factory=list)
    # HiG data blocks referenced by the plugins: (category, id) -> (offset, size in qwords)
    data: dict[tuple[int, int], tuple[int, int]] = field(default_factory=dict)
    nodes: int = 0  # Hrchy node count
    key_times: list[int] = field(default_factory=list)  # Anime key frame times

    @property
    def animated(self) -> bool:
        return any(name == "Anime" for name, _ in self.plugins)


@dataclass
class MapMember:
    sections: list[tuple[int, int]]
    width: int
    height: int
    tiles: list[int]
    models: list[MapModel]

    @property
    def stage_objects(self) -> list[MapModel]:
        """Stage objects in script order: 0x46 m is ``stage_objects[m]``."""
        return list(self.models)

    def tile(self, x: int, y: int) -> tuple[int, int]:
        """(signed height, terrain record index) of tile (x, y)."""
        word = self.tiles[y * self.width + x]
        low = word & 0xFF
        return (low - 0x100 if low & 0x80 else low), word >> 8


def member_for_map(map_id: int) -> int:
    return map_id + 1


def member_offsets(slps: bytes) -> tuple[int, ...]:
    return struct.unpack_from(f"<{MEMBER_COUNT + 1}I", slps, MEMBER_TABLE_OFFSET)


def _plugin_directory(data: bytes, start: int, end: int) -> tuple[int, list[tuple[str, int]]] | None:
    """Find the HiG plugin directory of a model section (first ``Frame`` entry)."""
    position = data.find(b"Frame\0\0\0", start, end)
    if position < 4:
        return None
    count = struct.unpack_from("<I", data, position - 4)[0]
    if not 1 <= count <= 16 or position + 16 * count > end:
        return None
    plugins = []
    for k in range(count):
        raw_name = data[position + 16 * k : position + 16 * k + 8].split(b"\0")[0]
        offset = struct.unpack_from("<I", data, position + 16 * k + 12)[0]
        if raw_name.isalnum():
            plugins.append((raw_name.decode("ascii"), offset))
    return position - 4, plugins


HIG_CATEGORIES = {1: "micro", 2: "tex2d", 3: "shape", 4: "hrchy", 5: "anime", 6: "share"}


def _hig_data(data: bytes, directory: int, plugins: list[tuple[str, int]], end: int) -> dict[tuple[int, int], tuple[int, int]]:
    """Data blocks referenced by the plugin blocks.

    Offsets in the directory and in the references count from ``directory - 0xc``.
    A plugin block is a 16-byte header (HiG type: 1, 1, category, 0, u16 id, 0,
    revision; then 0 and the row count), a row with the plugin's own code, then
    16-byte references (HiG type, u32 offset, 0).  A data block starts with the
    same kind of header whose last word is its size in qwords.
    """
    base = directory - 0xC
    blocks: dict[tuple[int, int], tuple[int, int]] = {}
    for _name, offset in plugins:
        block = base + offset
        if block + 16 > end:
            continue
        rows = struct.unpack_from("<I", data, block + 12)[0]
        for k in range(2, min(rows, 64)):
            ref = data[block + 16 * k : block + 16 * k + 16]
            if len(ref) < 16 or ref[0] != 1 or ref[1] != 1:
                break
            category, ident = ref[2], struct.unpack_from("<H", ref, 4)[0]
            target = base + struct.unpack_from("<I", ref, 8)[0]
            if target + 16 <= len(data) and data[target] == 1 and data[target + 2] == category:
                blocks[(category, ident)] = (target, struct.unpack_from("<I", data, target + 12)[0])
    return blocks


def _hig_details(data: bytes, blocks: dict[tuple[int, int], tuple[int, int]]) -> tuple[int, list[int]]:
    nodes, times = 0, []
    if (4, 1) in blocks:  # Hrchy: count row (0, 0, flags, node count)
        nodes = struct.unpack_from("<I", data, blocks[(4, 1)][0] + 28)[0]
    if (5, 2) in blocks:  # Anime key times: count row, then (kind, 0, offset, keys) and the times
        start, size = blocks[(5, 2)]
        keys = struct.unpack_from("<I", data, start + 44)[0]
        if keys and 48 + 4 * keys <= 16 * size:
            times = list(struct.unpack_from(f"<{keys}I", data, start + 48))
    return nodes, times


def parse_member(data: bytes) -> MapMember:
    count, header_size = struct.unpack_from("<2I", data, 0)
    if not 2 <= count <= 32 or header_size != (12 + 8 * count + 15) & ~15:
        raise ValueError(f"not a map member header (count {count}, header {header_size:#x})")
    sections, previous = [], 0
    for k in range(count):
        size, end = struct.unpack_from("<2I", data, 12 + 8 * k)
        if end != previous + size or end > len(data):
            raise ValueError(f"section {k} does not follow the previous one")
        sections.append((previous, end))
        previous = end
    width, height = struct.unpack_from("<2I", data, header_size)
    tiles_start = header_size + 8
    if tiles_start + 2 * width * height > sections[0][1]:
        raise ValueError("tile words run past section 0")
    tiles = list(struct.unpack_from(f"<{width * height}H", data, tiles_start))
    models = []
    for k, (start, end) in enumerate(sections[2:], start=2):
        directory = _plugin_directory(data, start, end)
        model = MapModel(index=k, start=start, end=end, plugins=directory[1] if directory else [])
        if directory:
            model.data = _hig_data(data, directory[0], directory[1], end)
            model.nodes, model.key_times = _hig_details(data, model.data)
        models.append(model)
    return MapMember(sections=sections, width=width, height=height, tiles=tiles, models=models)
