"""Read-only layout of a decoded MAPMODEL map member.

``MAP/MAPMODEL.BIN`` members 0..80 are battle maps (member n = map n, the value
a STAGE entry writes to ``0x524b00``); members 81..195 are world-map title
pictures (see ``docs/MAPMODEL_WORLD_MAP_TITLES.md``).  A decoded map member is:

* a header of ``u32`` words: section count, header size, 0, then one
  (size, end offset) pair per section, the ends accumulating from 0;
* in section 0, right after the pairs, the map width and height followed by one
  ``u16`` per tile (terrain cell words, meaning not decoded here);
* section 1: terrain-name records (0x1C bytes, see ``terrain_names.py``);
* sections 2..: one model each.  A model starts with a transform header (floats:
  scale, rotation, position) and then a Sony HiG plugin directory, a ``u32``
  count followed by 16-byte entries ``name[8], u32 0, u32 offset`` (Frame, Micro,
  Shape, Hrchy, Tex2d, then Anime and Share on animated models).

The first model is the static terrain mesh.  The animated models after it are the
stage objects that script opcode ``0x46 m,...`` and the entry initialisers
``0x146280`` / ``0x146160`` address as m = 0, 1, ...; a stage may initialise more
indices than its map has, which the Original then ignores.
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
        """Animated models in script order (0x46 m = position in this list)."""
        return [model for model in self.models if model.animated]


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
        models.append(MapModel(index=k, start=start, end=end, plugins=directory[1] if directory else []))
    return MapMember(sections=sections, width=width, height=height, tiles=tiles, models=models)
