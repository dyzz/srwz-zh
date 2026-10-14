"""Compile per-scene stage-fidelity timelines into native SP map-script records.

Each gallery row carries a ``fidelity`` block ported from the Original STAGE
script window around its effect call.  Timeline operations map one-to-one to
SP interpreter records (FUN_001785b0 / ext ops FUN_001c2e30).  Unit and pilot
numbers in the configuration are already SP definition IDs; the Original IDs
and the mapping evidence are kept beside them for review.

Opcode semantics used here (SP SLPS_259.20, verified by decompilation):
  0x01 a          wait a frames
  0x43 a          load + play BGM a (FUN_00182fc0(a, b, c, 1, 3, 0))
  bgm_pause       native FUN_00183220(2): pause the current BGM (cmd 0x20)
  0x46 m,k,v      stage model m: k=9 visibility, k=5 frame, k=6 range
  0x56 / +rec     dynamic effect at tile (two records)
  0x57            wait until no dynamic effect is active
  0x0d p,2        spawn list p, appear on map (FUN_001b4d90)
  0x14 f          native callback f
  0x12 n,0        set stage flag n (bitset 0x5dbc40)
  0x18 6,x,y      camera centre tile
  0x1388 v,0,d    assign; d=0x910e<pilot> actor visible, 0x910ef0<side> by side
  0x138d/0x138e   while var != value / end
  0x1390/0x1391   var += / -= value
  0x13ae 2<<16|p  remove the map actor carrying pilot p (kind 1: unit id)
  0x13b0          screen tint overlay (a=0x10000 on, 0 off)
  0x13b9 z,0      camera zoom (DAT_00457748) set immediately
  0x13bf 1,1<<16|u  register Gravion combination for unit u (FUN_001c2ba0)
  0x1395 a,b,c    placeholder actor table entry b>>16, mode b&0xffff,
                  stage flag op c>>16 (1 set, 3 clear)
"""

from __future__ import annotations

from typing import Any, Callable, Sequence

VAR_FADE = 0x8001
IMMEDIATE = 0x90000000


def _imm(value: int) -> int:
    if not -0x8000 <= value <= 0xFFFF:
        raise ValueError(f"immediate {value} outside the 16-bit script operand")
    return IMMEDIATE | (value & 0xFFFF)


def _u32(value: int) -> int:
    return value & 0xFFFFFFFF


def _tile(value: Sequence[int], label: str) -> tuple[int, int]:
    if len(value) != 2 or any(type(v) is not int or not 0 <= v <= 255 for v in value):
        raise ValueError(f"{label}: invalid tile {value!r}")
    return value[0], value[1]


def _id(value: Any, label: str, limit: int = 0x7FFF) -> int:
    if type(value) is not int or not 0 <= value <= limit:
        raise ValueError(f"{label}: invalid id {value!r}")
    return value


def spawn_record(unit: dict[str, Any], squad_name: str) -> list[str]:
    """One 32-byte native spawn-list record (FUN_001b4d90 layout).

    +0 class, +1 2, +2 appear (0xff animated, 0/1/2 altitude layer), +4/+6
    anchor pilot/unit (-1), +8 -2, +0xc x, +0xd y, +0xe facing, +0xf side,
    +0x10 pilots, +0x16 units, +0x1c squad-name pointer.
    """
    x, y = _tile(unit["tile"], "spawn tile")
    head = unit.get("class", 4)
    appear = unit.get("appear", 1)
    facing = unit.get("facing", 0)
    side = unit.get("side", 0)
    if appear not in (0, 1, 2, 0xFF):
        raise ValueError("appear must be 0, 1, 2 or 0xff")
    if not 0 <= facing <= 15 or not 0 <= side <= 15 or not 0 <= head <= 0xFE:
        raise ValueError("invalid spawn facing, side or class")
    pilot = _id(unit["pilot"], "spawn pilot")
    unit_id = _id(unit["unit"], "spawn unit")
    words = [
        head | (2 << 8) | (appear << 16),
        0xFFFFFFFF,
        0x0000FFFE,
        x | (y << 8) | (facing << 16) | (side << 24),
        pilot | (0xFFFF << 16),
        0xFFFF | (unit_id << 16),
        0xFFFFFFFF,
        squad_name,
    ]
    return ["    .word " + ",".join(str(w) for w in words)]


def compile_scene(row: int, fidelity: dict[str, Any], effect_tile: Sequence[int],
                  effects: Sequence[int]) -> dict[str, Any]:
    """Return {'script': [lines], 'data': [lines], 'receipt': {...}} for one row."""
    script: list[str] = []
    data: list[str] = []
    groups = fidelity.get("units", {})
    if not isinstance(groups, dict):
        raise ValueError(f"row {row}: units must map group names to unit lists")
    group_symbols: dict[str, tuple[str, str]] = {}
    for g_index, (name, units) in enumerate(groups.items()):
        if not units or len(units) > 8:
            raise ValueError(f"row {row}: unit group {name} must hold 1..8 units")
        prep = f"gallery_prep_{row}_{g_index}"
        pairs = f"gallery_pairs_{row}_{g_index}"
        spawn = f"gallery_spawn_{row}_{g_index}"
        group_symbols[name] = (prep, spawn)
        data += [".align 4", f"{prep}:",
                 f"    lui $a0,%hi({pairs})",
                 "    j gallery_prepare_units",
                 f"    addiu $a0,$a0,%lo({pairs})",
                 ".align 4", f"{pairs}:"]
        for unit in units:
            data.append(f"    .hword {_id(unit['unit'], 'unit')},{_id(unit['pilot'], 'pilot')}")
        data += ["    .hword 0xffff,0xffff", ".align 4", f"{spawn}:"]
        for unit in units:
            data += spawn_record(unit, "gallery_empty_squad_name")
        data += ["    .word 0xff,0,0,0,0,0,0,0"]

    ghost = fidelity.get("ghost_table")
    if ghost is not None:
        table = f"gallery_ghosts_{row}"
        install = f"gallery_ghost_install_{row}"
        data += [".align 4", f"{install}:",
                 f"    lui $a0,%hi({table})",
                 "    j 0x001c0f70",
                 f"    addiu $a0,$a0,%lo({table})",
                 ".align 4", f"{table}:"]
        for g_index, group in enumerate(ghost["groups"]):
            data.append(f"    .hword {len(group)},0")
            data.append(f"    .word {table}_g{g_index}")
        data.append("    .word 0,0")
        for g_index, group in enumerate(ghost["groups"]):
            data += [".align 2", f"{table}_g{g_index}:"]
            for entry in group:
                x, y = _tile(entry["tile"], "ghost tile")
                values = [_id(entry["unit"], "ghost unit"), x, y, entry["side"], entry.get("b8", 0),
                          entry["facing"], 0xFFFF, 0xFFFF, entry["flag"]]
                data.append("    .hword " + ",".join(str(v & 0xFFFF) for v in values))

    def word(*values: int | str) -> None:
        script.append("    .word " + ",".join(str(_u32(v)) if isinstance(v, int) else v for v in values))

    used_effects: list[int] = []
    for op in fidelity["timeline"]:
        kind, args = op[0], op[1:]
        if kind == "wait":
            word(1, _id(args[0], "wait", 0x7FFF), 0, 0)
        elif kind == "bgm":
            word(0x43, _id(args[0], "bgm", 0x65), 0, 0)
        elif kind == "bgm_pause":
            word(0x14, "gallery_bgm_pause", 0, 0)
        elif kind == "zoom":
            word(0x13B9, int(args[0]), 0, 0)
        elif kind == "camera":
            x, y = _tile(args, "camera")
            word(0x18, 6, x, y)
        elif kind == "effect":
            effect_id = _id(args[0], "effect")
            x, y = _tile(args[1] if len(args) > 1 else effect_tile, "effect tile")
            word(0x56, 6, 0, x | (y << 16))
            word(0, effect_id, 1, 0)
            used_effects.append(effect_id)
        elif kind == "wait_effects":
            word(0x57, 0, 0, 0)
        elif kind == "model":
            word(0x46, *(int(v) for v in args))
        elif kind == "spawn":
            prep, spawn = group_symbols[args[0]]
            word(0x14, prep, 0, 0)
            word(0x0D, spawn, 2, 0)
        elif kind == "visible":
            pilot, shown = _id(args[0], "pilot"), int(bool(args[1]))
            word(0x1388, _imm(shown), 0, 0x910E0000 | pilot)
        elif kind == "side_visible":
            side, shown = _id(args[0], "side", 15), int(bool(args[1]))
            word(0x1388, _imm(shown), 0, 0x910EF000 | side)
        elif kind == "remove_pilot":
            word(0x13AE, 0x20000 | _id(args[0], "pilot"), 0, 0)
        elif kind == "remove_unit":
            word(0x13AE, 0x10000 | _id(args[0], "unit"), 0, 0)
        elif kind == "fade":
            start, end, step = (int(v) for v in args)
            if step == 0 or (end - start) % step:
                raise ValueError(f"row {row}: fade step must reach its end value")
            word(0x1388, _imm(start), 0, VAR_FADE)
            word(0x138D, VAR_FADE, 0x801, _imm(end))
            word(0x13B0, 0x10000, 0x80018001, 0x80018001)
            word(0x1390 if step > 0 else 0x1391, _imm(abs(step)), 0, VAR_FADE)
            word(1, 1, 0, 0)
            word(0x138E, 0, 0, 0)
        elif kind == "overlay":
            word(0x1388, _imm(int(args[0])), 0, VAR_FADE)
            word(0x13B0, 0x10000, 0x80018001, 0x80018001)
        elif kind == "overlay_off":
            word(0x13B0, 0, 0, 0)
        elif kind == "ghosts_install":
            if ghost is None:
                raise ValueError(f"row {row}: ghost install without a ghost table")
            word(0x14, f"gallery_ghost_install_{row}", 0, 0)
            for flag in ghost["visible_flags"]:
                word(0x12, _id(flag, "flag", 0x3FF), 0, 0)
            word(0x1395, 0, 0, 0)
        elif kind == "ghost":
            entry, mode, flag_op = (int(v) for v in args)
            word(0x1395, 0, (entry << 16) | mode, flag_op << 16)
        elif kind == "combine":
            word(0x13BF, 1, 0x10000 | _id(args[0], "unit"), 0)
        elif kind == "raw":
            word(*(int(v) for v in args))
        else:
            raise ValueError(f"row {row}: unknown timeline operation {kind!r}")
    if sorted(set(used_effects)) != sorted(set(effects)):
        raise ValueError(f"row {row}: timeline effects {used_effects} differ from catalog {list(effects)}")
    return {"script": script, "data": data,
            "receipt": {"records": len(script), "unit_groups": list(groups),
                        "ghost_table": ghost is not None}}
