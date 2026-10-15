"""Generate native map and event-script tables for the SP event gallery.

The assembly runtime owns scene loading and return to the retained theater list.
This module consumes the product configuration in menu order; it does not rely
on a reverse-engineering workspace or a saved emulator state.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

try:
    from .fidelity import compile_scene
except ImportError:  # executed as a script
    from fidelity import compile_scene


def _tile(value: Any, label: str) -> tuple[int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{label} must contain two tile coordinates")
    if any(type(v) is not int or not 0 <= v <= 255 for v in value):
        raise ValueError(f"{label} coordinates must be integers from 0 to 255")
    return value[0], value[1]


def generate(entries: Sequence[dict[str, Any]], outdir: Path | str,
             voice_timelines: dict[int, bytes] | None = None) -> dict[str, Any]:
    """Write ``gallery-scenes.inc`` and return the static configuration receipt.

    An unresolved effect anchor explicitly uses the configured camera tile until
    the product configuration supplies the original unit's coordinate. A missing
    initial map view explicitly defaults to 3. Both choices appear in the receipt
    and the native row flags rather than silently producing an inactive item.
    """
    if not 1 <= len(entries) <= 32:
        raise ValueError("gallery requires 1 to 32 scenes (native table budget)")
    lines = [
        "/* Generated from the product event-gallery configuration. */",
        f".equ GALLERY_SCENE_COUNT, {len(entries)}",
        ".org 0x1c00",
        ".globl gallery_scene_table",
        "gallery_scene_table:",
    ]
    scenes: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        scene_id = entry["id"]
        map_id = entry["map"]
        if type(map_id) is not int or map_id < 0:
            raise ValueError(f"{scene_id}: invalid map id")
        camera_tile = _tile(entry["camera"]["tile"], f"{scene_id}: camera")
        effect_tile = entry.get("effect_tile")
        fallback_anchor = effect_tile is None
        effect_tile = camera_tile if fallback_anchor else _tile(effect_tile, f"{scene_id}: effect")
        map_view = entry["camera"].get("map_view")
        fallback_view = map_view is None
        if fallback_view:
            map_view = 3
        if type(map_view) is not int or not 0 <= map_view <= 0x7FFF:
            raise ValueError(f"{scene_id}: invalid initial map view")
        effects = entry["effects"]
        if not effects or any(type(e) is not int or not 0 <= e <= 0x7FFF for e in effects):
            raise ValueError(f"{scene_id}: invalid native effect ids")
        if effects[0] == 273 and list(effects) != [273, 274]:
            raise ValueError("Impulse scene must preserve the 273 then 274 chain")
        # The scene's primary effect carries its voice schedule; a pre-beat
        # effect (a unit burst before the performance) may precede it.
        primary = next((e for e in effects if voice_timelines and e in voice_timelines), effects[0])
        flags = int(fallback_anchor) | (int(fallback_view) << 1)
        lines += [
            f"    /* row {index}: {scene_id} */",
            "    .word " + ",".join(map(str, (
                map_id, *camera_tile, map_view, f"gallery_script_{index}",
                flags, primary, f"gallery_voice_{index}" if voice_timelines and primary in voice_timelines else 0,
            ))),
        ]
        scenes.append({
            'primary': primary,
            "row": index,
            "id": scene_id,
            "map": map_id,
            "camera_tile": list(camera_tile),
            "map_view": map_view,
            "camera_view_defaulted_to_3": fallback_view,
            "effect_tile": list(effect_tile),
            "effect_anchor_uses_camera_placeholder": fallback_anchor,
            "effects": list(effects),
            "stage_objects": entry.get("stage_objects", []),
            "stage_object_initialization": (
                "explicit Original native model frames, modes and visibility from stage_objects"
                if entry.get("stage_objects") else "no additional native model initializer found"
            ),
        })

    # Voice schedules, stage-object initializers and shared data stay below the
    # caption table (0x825800); scene scripts live after it at 0x826800.
    lines += [".org 0x2000"]
    if voice_timelines:
        for scene in scenes:
            timeline = voice_timelines.get(scene['primary'])
            if timeline is None:
                continue
            assert len(timeline) <= 80 and len(timeline) % 4 == 0
            padded = timeline + bytes(80 - len(timeline))
            lines += ['.align 4', f"gallery_voice_{scene['row']}:",
                      '    .byte ' + ','.join(map(str, padded))]
    lines += ['.align 4', 'gallery_empty_squad_name:', '    .word 0', 'gallery_stage_objects:']
    for scene in scenes:
        lines.append(f"    .word gallery_objects_{scene['row']}" if scene['stage_objects'] else "    .word 0")
    for scene in scenes:
        if not scene['stage_objects']:
            continue
        lines += [f"gallery_objects_{scene['row']}:"]
        for obj in scene['stage_objects']:
            lines.append("    .word " + ",".join(str(obj[k]) for k in ('model', 'frame', 'mode', 'visible')))
        lines.append("    .word -1,0,0,0")
    lines += ["gallery_low_data_end:", ".org 0x4800", ".globl gallery_script", "gallery_script:"]
    data_lines: list[str] = []
    for scene, entry in zip(scenes, entries):
        index = scene["row"]
        compiled = compile_scene(index, entry["fidelity"], scene["effect_tile"], scene["effects"])
        lines += [".align 4", f"gallery_script_{index}:"] + compiled["script"]
        lines.append("    .word " + ",".join(map(str, (0x14, "gallery_finish", 0, 0))))
        # The callback switches phase; park here until the next frame cleans up.
        lines.append("    .word 1,32767,0,0")
        data_lines += compiled["data"]
        scene["fidelity"] = {k: v for k, v in entry["fidelity"].items() if k != "timeline"}
        scene["fidelity"]["compiled"] = compiled["receipt"]
    lines += data_lines
    receipt = {
        "schema_version": 1,
        "entries": scenes,
        "voice_timeline_initialization": "Source CCC schedules copied into the native shared voice table during gallery playback",
        "boundary": (
            "Static native runtime configuration compiled from per-scene Original STAGE "
            "timelines. Runtime fidelity must be verified independently in the emulator."
        ),
    }
    output = Path(outdir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "gallery-scenes.inc").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (output / "runtime-scenes.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("outdir", type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    receipt = generate(config["entries"], args.outdir)
    print(f"Generated {len(receipt['entries'])} native gallery scripts")


if __name__ == "__main__":
    main()
