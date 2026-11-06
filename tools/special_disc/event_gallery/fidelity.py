"""Compile per-scene stage-fidelity timelines into native SP map-script records.

Each gallery row carries a ``fidelity`` block ported from the Original STAGE
script window around its effect call.  Timeline operations map one-to-one to
SP interpreter records (FUN_001785b0 / ext ops FUN_001c2e30).  Unit and pilot
numbers in the configuration are already SP definition IDs; the Original IDs
and the mapping evidence are kept beside them for review.

Opcode semantics used here (SP SLPS_259.20, verified by decompilation):
  0x01 a          wait a frames (a >= 1: 0x01 0 never ends)
  wait_modes t,c  0x01 t with triangle (dialogue), 0x01 c with circle (effects
                  only): runtime.S gallery_talk_mode sets the operand at scene start
  circle_skip_to m [ops] / mark m  circle mode jumps forward to mark m:
                  mode words lay "0x14 gallery_skip, 0, m" (after the optional
                  circle-only ops) over the first records of the skipped part,
                  so triangle keeps its records and timing unchanged
  circle_tile / circle_facing (unit fields)  the spawn tile / facing circle
                  mode uses instead (mode word on the spawn record)
  circle_camera [x, y] (fidelity field)  the tile circle mode opens on (runtime.py:
                  mode words on the scene table's camera, read by map initialization)
  0x43 a          load + play BGM a (FUN_00182fc0(a, b, c, 1, 3, 0)); the script
                  waits until the stream is ready. Circle mode (mode words, outside
                  circle_skip_to parts) calls runtime.S gallery_bgm_nowait instead
  bgm_pause       native FUN_00183220(2): pause the current BGM (cmd 0x20)
  circle_effect_bgm  tracks whose bgm op pauses instead of playing in circle mode: the
                  next effect's resource header starts the music
  circle_bgm_release  one frame in triangle mode; circle mode calls FUN_0018abe0, which
                  starts a song the effect header loaded but never releases (start 0)
  form_se         native FUN_00182a50(0x2a, 1): the form-change sound of op 0x1d
  0x46 m,k,v      stage model m: k=9 visibility (v 0 hide, 1 show), k=5 animate
                  to frame v, k=7 set frame v now, k=6/8 frame with high half
  0x56 / +rec     dynamic effect at tile (two records)
  effect_shift    runtime.S gallery_effect_shift: move the running effect by world
                  units (x, z), a fraction of a tile (0.5)
  0x57            wait until no dynamic effect is active
  0x0d p,m        spawn list p, appear on map (FUN_001b4d90); m is 2 unless the
                  timeline gives the stage's own (``["spawn", g, 1]``); a record whose
                  pilot is already on the map moves that actor, so generic
                  enemy pilots go through ``deploy`` instead
  deploy          native gallery_deploy: the stage spawn-group engine
                  (FUN_00181a20, op 0x05 n with 0x8000) on gallery-owned tables;
                  every member gets its own unit and pilot objects
  0x14 f          native callback f (the per-frame driver moves on next frame
                  whatever f returns; f may redirect 0x61deb8 itself)
  0x52 a / 0x54   gosub a / return (stack 0x61ded0, depth 0x61def0); circle
                  mode gosubs runtime.S gallery_quiet_sub for each talk op
  0x12 n,0        set stage flag n (bitset 0x5dbc40); 0x12 n,1 clears it
  speakers        native callback: install a speaker cursor table at 0x61e1a8
                  (FUN_0017c540; restored with the other state regions)
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

import struct
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
    +0x10 pilots, +0x16 units, +0x1c squad-name pointer. Optional ``members``
    (up to two {unit, pilot}) fill the squad's second and third slots; a unit's
    optional ``crew`` (pilot ids) are seated in it by gallery_prepare_units.
    """
    head = unit.get("class", 4)
    appear = unit.get("appear", 1)
    facing = unit.get("facing", 0)
    side = unit.get("side", 0)
    if appear not in (0, 1, 2, 0xFF):
        raise ValueError("appear must be 0, 1, 2 or 0xff")
    if not 0 <= facing <= 15 or not 0 <= side <= 15 or not 0 <= head <= 0xFE:
        raise ValueError("invalid spawn facing, side or class")
    members = unit.get("members", [])
    if len(members) > 2:
        raise ValueError("a squad holds at most two members besides its leader")
    slots = [unit] + members + [None] * (2 - len(members))
    pilots = [0xFFFF if m is None else _id(m["pilot"], "spawn pilot") for m in slots]
    units = [0xFFFF if m is None else _id(m["unit"], "spawn unit") for m in slots]
    words = [
        head | (2 << 8) | (appear << 16),
        0xFFFFFFFF,
        0x0000FFFE,
        _spawn_place(unit),
        pilots[0] | (pilots[1] << 16),
        pilots[2] | (units[0] << 16),
        units[1] | (units[2] << 16),
        squad_name,
    ]
    return ["    .word " + ",".join(str(w) for w in words)]


def _spawn_place(unit: dict[str, Any]) -> int:
    """Spawn-record word +0xc: x, y, facing, side."""
    x, y = _tile(unit["tile"], "spawn tile")
    return x | (y << 8) | (unit.get("facing", 0) << 16) | (unit.get("side", 0) << 24)


def deploy_tables(squads: Sequence[dict[str, Any]], label: str) -> list[str]:
    """Spawn-group tables in the stage-entry layout read by FUN_00181810.

    One group (first record 0, member count) over 22-byte member records
    (half-words: squad, squad, unit, 0, pilot, level, level, 0, 0, 0, flags, as
    in the Original STAGE groups; ``level`` defaults to 1 and ``flags`` to 0;
    enhancement parts are left out because item ids differ between the games)
    and 29-byte squads (side, Shift-JIS name in bytes 1-23, ``squad_flags``
    (default 0x10), x, y, facing, layer 0).  A squad's optional ``members``
    (up to two {unit, pilot}) follow its leader with the same squad index.
    """
    records, squad_bytes = [], []
    for index, squad in enumerate(squads):
        x, y = _tile(squad["tile"], "deploy tile")
        facing, side = squad.get("facing", 0), squad.get("side", 12)
        if not 0 <= facing <= 15 or not 0 <= side <= 15:
            raise ValueError("invalid deploy facing or side")
        members = squad.get("members", [])
        if len(members) > 2:
            raise ValueError("a squad holds at most two members besides its leader")
        for member in [squad] + members:
            level, flags = member.get("level", 1), member.get("flags", 0)
            if not 1 <= level <= 99 or not 0 <= flags <= 0xFF:
                raise ValueError("invalid deploy level or flags")
            records.append([index, index, _id(member["unit"], "deploy unit"), 0,
                            _id(member["pilot"], "deploy pilot"), level, level, 0, 0, 0, flags])
        name = squad.get("name", "").encode("cp932")
        if len(name) > 22:
            raise ValueError(f"squad name {squad['name']!r} longer than 22 bytes")
        squad_flags = squad.get("squad_flags", 0x10)
        if not 0 <= squad_flags <= 0xFF:
            raise ValueError("invalid squad flags")
        squad_bytes.append(bytes([side]) + name.ljust(23, b"\0") + bytes([squad_flags, x, y, facing, 0]))
    lines = [".align 4", f"{label}:", f"    .word {label}_records,{label}_squads,{label}_groups",
             f"{label}_groups:", f"    .hword 0,0,{len(records)},0", f"{label}_records:"]
    lines += ["    .hword " + ",".join(str(v) for v in record) for record in records]
    lines.append(f"{label}_squads:")
    lines += ["    .byte " + ",".join(str(b) for b in squad) for squad in squad_bytes]
    return lines


SPEAKER_KINDS = {"unit_kind0": 0, "unit": 1, "pilot": 2, "tile": 3, "pilot_offset": 4, "no_cursor": 5}


def speaker_table(entries: Sequence[dict[str, Any]], label: str) -> list[str]:
    """Speaker cursor table in the stage layout read by FUN_0017c540 (pointer 0x61e1a8).

    Eight half-words per entry: speaker pilot, flags | kind << 8, target (32-bit
    id, or x then 0 for a tile), y or offset dx, offset dy, condition stage
    flag (0 = none), 0; -1 ends the table.  ``tools.srwz.stage_events.
    speaker_positions`` reads the Original tables in the same terms.
    """
    lines = [".align 4", f"{label}:"]
    for e in entries:
        kind = SPEAKER_KINDS[e["kind"]]
        speaker = e["speaker"]
        if not (speaker == -2 or 0 <= speaker <= 0x7FFF):
            raise ValueError(f"invalid speaker {speaker!r}")
        x = y = dy = 0
        if e["kind"] == "tile":
            x, y = _tile(e["tile"], "speaker tile")
        elif e["kind"] == "pilot_offset":
            x = _id(e["pilot"], "speaker offset pilot")
            y, dy = (int(v) for v in e["offset"])
        elif e["kind"] in ("unit_kind0", "unit", "pilot"):
            x = _id(e["target"], "speaker target")
        flag = e.get("condition_flag") or 0
        words = [speaker, (e.get("flags", 0) & 0xFF) | (kind << 8), x & 0xFFFF, x >> 16, y, dy, flag, 0]
        lines.append("    .hword " + ",".join(str(w & 0xFFFF) for w in words))
    lines.append("    .hword 0xffff,0,0,0,0,0,0,0")
    return lines


def compile_scene(row: int, fidelity: dict[str, Any], effect_tile: Sequence[int],
                  effects: Sequence[int]) -> dict[str, Any]:
    """Return {'script', 'data', 'far_data' (placed after the packet buffer), 'talk_ops', 'mode_words', 'receipt'} for one row."""
    script: list[str] = []
    data: list[str] = []
    mode_words: list[tuple[str, int, int]] = []
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
            for member in [unit] + unit.get("members", []):
                data.append(f"    .hword {_id(member['unit'], 'unit')},{_id(member['pilot'], 'pilot')}")
                # sub-pilots seated in the same unit (0xfffe: next free seat)
                for crew in member.get("crew", []):
                    data.append(f"    .hword 0xfffe,{_id(crew, 'crew pilot')}")
        data += ["    .hword 0xffff,0xffff", ".align 4", f"{spawn}:"]
        for k, unit in enumerate(units):
            data += spawn_record(unit, "gallery_empty_squad_name")
            if "circle_tile" in unit or "circle_facing" in unit:
                circle = {**unit, "tile": unit.get("circle_tile", unit["tile"]),
                          "facing": unit.get("circle_facing", unit.get("facing", 0))}
                # +0xc x, y, facing, side
                mode_words.append((f"{spawn}+{32 * k + 12}", _spawn_place(unit), _spawn_place(circle)))
        data += ["    .word 0xff,0,0,0,0,0,0,0"]

    deploy_symbols: dict[str, str] = {}
    # Spawn-group tables are read only by the native spawn during gallery_deploy,
    # so they go with the map-dialogue blocks after the packet buffer (far data).
    far_data: list[str] = []
    deploy = fidelity.get("deploy", {})
    if not isinstance(deploy, dict):
        raise ValueError(f"row {row}: deploy must map group names to squad lists")
    for g_index, (name, squads) in enumerate(deploy.items()):
        if not squads or len(squads) > 16:
            raise ValueError(f"row {row}: deploy group {name} must hold 1..16 squads")
        call, table = f"gallery_deploy_{row}_{g_index}", f"gallery_deploy_table_{row}_{g_index}"
        deploy_symbols[name] = call
        data += [".align 4", f"{call}:",
                 f"    lui $a0,%hi({table})",
                 "    j gallery_deploy",
                 f"    addiu $a0,$a0,%lo({table})"]
        far_data += deploy_tables(squads, table)

    speaker_symbols: dict[str, str] = {}
    speakers = fidelity.get("speakers", {})
    if not isinstance(speakers, dict):
        raise ValueError(f"row {row}: speakers must map table names to entry lists")
    for t_index, (name, entries) in enumerate(speakers.items()):
        call, table = f"gallery_speakers_{row}_{t_index}", f"gallery_speaker_table_{row}_{t_index}"
        speaker_symbols[name] = call
        data += [".align 4", f"{call}:",
                 f"    lui $a0,%hi({table})",
                 "    addiu $a0,$a0,%lo({table})".replace("{table}", table),
                 "    lui $t0,0x0062",
                 "    jr $ra",
                 "    sw $a0,-0x1e58($t0)"]
        far_data += speaker_table(entries, table)

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

    # Circle-mode records still to lay over the next script records (circle_skip_to).
    overlay: list[list[str]] = []
    overlaid = [0]

    def word(*values: int | str) -> None:
        rendered = [str(_u32(v)) if isinstance(v, int) else v for v in values]
        if overlay:
            # Circle mode rewrites a talk record's words before the mode words
            # apply, so over a talk record every word is laid, equal or not.
            talk_record = bool(script) and script[-1].startswith("gallery_talkop_")
            label = f"gallery_circlerec_{row}_{overlaid[0]}"
            overlaid[0] += 1
            script.append(f"{label}:")
            for k, (triangle, circle) in enumerate(zip(rendered, overlay.pop(0))):
                if triangle != circle or talk_record:
                    mode_words.append((f"{label}+{4 * k}", triangle, circle))
        script.append("    .word " + ",".join(rendered))

    used_effects: list[int] = []
    talk_ops: list[tuple[str, int, int, bool]] = []
    timeline = fidelity["timeline"]
    marks = [op[1] for op in timeline if op[0] == "mark"]
    if len(set(marks)) != len(marks):
        raise ValueError(f"row {row}: duplicate timeline mark")
    skipping = None
    last_effect = max((k for k, op in enumerate(timeline) if op[0] == "effect"), default=len(timeline))
    for position, op in enumerate(timeline):
        kind, args = op[0], op[1:]
        if kind == "wait":
            word(1, _id(args[0], "wait", 0x7FFF), 0, 0)
        elif kind == "circle_bgm_release":
            # An effect whose header gives no start frame expects its song to be
            # playing already; in circle mode start it here, as the native cue does.
            label = f"gallery_modewait_{row}_{len(mode_words)}"
            mode_words += [(f"{label}+0", "1", "20"), (f"{label}+4", "1", str(0x18ABE0))]
            script.append(f"{label}:")
            word(1, 1, 0, 0)
        elif kind == "wait_modes":
            triangle, circle = _id(args[0], "wait", 0x7FFF), _id(args[1], "wait", 0x7FFF)
            if min(triangle, circle) < 1:
                raise ValueError(f"row {row}: op 0x01 0 never ends; wait at least one frame")
            label = f"gallery_modewait_{row}_{len(mode_words)}"
            mode_words.append((f"{label}+4", triangle, circle))
            script.append(f"{label}:")
            word(1, triangle, 0, 0)
        elif kind == "bgm":
            track = _id(args[0], "bgm", 0x65)
            if not overlay:
                # Circle mode starts the track without the ~40-frame stream wait.
                label = f"gallery_bgm_{row}_{position}"
                # An effect that starts this song itself only needs the theater track
                # out of the way: playing it here too would restart it seconds later.
                starter = "gallery_bgm_pause" if track in fidelity.get("circle_effect_bgm", ()) else "gallery_bgm_nowait"
                mode_words += [(f"{label}+0", "67", "20"), (f"{label}+4", str(track), starter),
                               (f"{label}+12", "0", str(track))]
                script.append(f"{label}:")
            word(0x43, track, 0, 0)
        elif kind == "bgm_pause":
            word(0x14, "gallery_bgm_pause", 0, 0)
        elif kind == "form_se":
            word(0x14, "gallery_form_se", 0, 0)
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
        elif kind == "effect_shift":
            word(0x14, "gallery_effect_shift", *struct.unpack("<2I", struct.pack("<2f", *args)))
        elif kind == "wait_effects":
            word(0x57, 0, 0, 0)
        elif kind == "model":
            word(0x46, *(int(v) for v in args))
        elif kind == "spawn":
            prep, spawn = group_symbols[args[0]]
            word(0x14, prep, 0, 0)
            word(0x0D, spawn, int(args[1]) if len(args) > 1 else 2, 0)
        elif kind == "deploy":
            word(0x14, deploy_symbols[args[0]], 0, 0)
        elif kind == "speakers":
            word(0x14, speaker_symbols[args[0]], 0, 0)
        elif kind == "flag":
            flag, value = _id(args[0], "flag", 0x3FF), int(bool(args[1]))
            word(0x12, flag, 0 if value else 1, 0)
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
        elif kind == "talk_install":
            word(0x14, f"gallery_talk_install_{row}", 0, 0)
        elif kind == "talk":
            # Native map dialogue section n (op 0x0f) from the installed block.
            # Labelled: the runtime turns it into a non-yielding no-op when the scene
            # is entered with circle (effects only) and restores it for triangle.
            section, cursor = _id(args[0], "talk section", 0x7FFF), int(args[1]) if len(args) > 1 else 0
            label = f"gallery_talkop_{row}_{len(talk_ops)}"
            # A camera op onto a unit right after the section (0x18 1/2) moves the
            # camera and the cursor there, so circle mode skips replaying the
            # section's cursor moves: the replay would only flash the last speaker's
            # tile before the cut. 0x18 6 (tile) leaves the cursor where it was.
            # Sections after the last effect are not replayed either: without the
            # text the camera would only hop between speakers (and back) at the end.
            following = timeline[position + 1] if position + 1 < len(timeline) else None
            superseded = following is not None and following[0] == "raw" and \
                following[1] == 0x18 and following[2] in (1, 2) or position > last_effect
            talk_ops.append((label, section, cursor, superseded))
            script.append(f"{label}:")
            word(0x0F, section, 0, cursor)
        elif kind == "raw":
            word(*(int(v) for v in args))
        elif kind == "circle_skip_to":
            name, extra = args[0], (args[1] if len(args) > 1 else [])
            if ["mark", name] not in timeline[position + 1:]:
                raise ValueError(f"row {row}: circle_skip_to {name!r} has no later mark")
            if overlay:
                raise ValueError(f"row {row}: circle_skip_to {name!r} overlaps the previous skip")
            lines = compile_scene(row, {"timeline": extra}, effect_tile, [])["script"] if extra else []
            if any(not line.startswith("    .word ") for line in lines):
                raise ValueError(f"row {row}: circle-only ops must be plain records")
            overlay += [line[10:].split(",") for line in lines]
            overlay.append(["20", "gallery_skip", "0", f"gallery_mark_{row}_{name}"])
            skipping = name
        elif kind == "mark":
            if overlay and skipping == args[0]:
                raise ValueError(f"row {row}: the part before mark {args[0]!r} is shorter than its circle records")
            script.append(f"gallery_mark_{row}_{args[0]}:")
        else:
            raise ValueError(f"row {row}: unknown timeline operation {kind!r}")
    if sorted(set(used_effects)) != sorted(set(effects)):
        raise ValueError(f"row {row}: timeline effects {used_effects} differ from catalog {list(effects)}")
    return {"script": script, "data": data, "far_data": far_data, "talk_ops": talk_ops,
            "mode_words": mode_words,
            "receipt": {"records": sum(1 for line in script if line.startswith("    .word")),
                        "unit_groups": list(groups), "ghost_table": ghost is not None,
                        "talk_ops": len(talk_ops), "mode_words": len(mode_words)}}
