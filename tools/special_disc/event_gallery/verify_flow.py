"""Verify native gallery transitions and identify screenshots by watched state."""
import argparse
from bisect import bisect_right
import hashlib
import json
from pathlib import Path
import re
import struct


WATCH = re.compile(
    r"WATCH frame (\d+) 0x(?:1f11f00|1ff1f00|821f00): ([0-9a-f]{32}) -> ([0-9a-f]{32})", re.I
)
INITIAL_WATCH = re.compile(r"watching 0x(?:1f11f00|1ff1f00|821f00) len 16 = ([0-9a-f]{32})", re.I)
SHOT = re.compile(r"SHOT (.+) (\d+)x(\d+) luma=([\d.]+)")
STAGES = {0: "gallery_idle", 1: "requested", 2: "playing", 3: "finished_pending_return"}
INTERVENTIONS = {"poke", "pokefile", "load", "effect", "call", "caption"}


def _state(value):
    row, phase, completed, _ = struct.unpack("<4I", bytes.fromhex(value))
    if phase not in STAGES:
        raise AssertionError(f"Unknown native gallery phase {phase}")
    return {"row": row, "phase": phase, "completed_row": completed}


def _scene(row, entries):
    if not 0 <= row < len(entries):
        raise AssertionError(f"Native gallery row {row} is outside the configured list")
    entry = entries[row]
    return {"row": row, "id": entry["id"], "name": entry["name"],
            "effects": entry["effects"], "map": entry["map"]}


def verify(journal, entries, *, require_complete=True):
    """Check a continuous watch, rejecting host writes or restored states.

    Screenshot filenames are descriptive user input, not scene evidence. The
    native row is the requested/last-played row; while phase is zero it does not
    report the list widget's current highlighted item.
    """
    journal = Path(journal)
    transitions, observations, captures = [], [], []
    errors, interventions = [], []
    current_state = None
    previous_frame = -1
    journal_bytes = journal.read_bytes()
    for line_number, line in enumerate(journal_bytes.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise AssertionError(f"Incomplete or invalid journal line {line_number}") from error
        frame = record["frame"]
        if frame < previous_frame:
            raise AssertionError("Journal frame counter reset; cannot combine emulator sessions")
        previous_frame = frame
        if "command" in record:
            command = record["command"].split()
            if command and command[0] in INTERVENTIONS:
                interventions.append({"line": line_number, "frame": frame,
                                      "command": record["command"]})
            if command and command[0] == "unwatch" and current_state is not None:
                raise AssertionError("Gallery watch was disabled; continuous transitions are required")
        for result_index, result in enumerate(record.get("result", [])):
            if result.startswith("ERR "):
                errors.append(result)
            initial = INITIAL_WATCH.fullmatch(result)
            if initial:
                state = _state(initial[1])
                if current_state is not None and state != current_state:
                    raise AssertionError("Reinstalled watch differs from the last observed gallery state")
                current_state = state
                observations.append({**state, "frame": frame, "line": line_number,
                                     "result_index": result_index, "initial_watch": True})
            match = WATCH.fullmatch(result)
            if match:
                before, after = _state(match[2]), _state(match[3])
                if current_state is None:
                    raise AssertionError("A gallery transition was recorded without its initial watch value")
                if before != current_state:
                    raise AssertionError(f"Discontinuous gallery watch at frame {match[1]}")
                transition = {**after, "frame": int(match[1]), "line": line_number,
                              "result_index": result_index}
                if transition["frame"] > frame:
                    raise AssertionError("Watch transition occurs after its journal result frame")
                if observations and transition["frame"] < observations[-1]["frame"]:
                    raise AssertionError("Gallery watch frames are not chronological")
                current_state = after
                transitions.append(transition)
                observations.append({**transition, "initial_watch": False})
            shot = SHOT.fullmatch(result)
            if shot:
                captures.append({"path": shot[1], "frame": frame,
                                 "line": line_number, "result_index": result_index,
                                 "width": int(shot[2]), "height": int(shot[3]),
                                 "luma": float(shot[4])})
    if errors:
        raise AssertionError(errors)
    if interventions:
        raise AssertionError(f"Host state intervention prevents natural-flow verification: {interventions}")
    if not observations or observations[0]["phase"] != 0:
        raise AssertionError("The gallery watch must begin in the list phase")

    runs = []
    active = None
    for transition in transitions:
        phase = transition["phase"]
        if phase == 1:
            if active is not None:
                raise AssertionError("A new selection started before the previous scene returned")
            active = {"run_index": len(runs), **_scene(transition["row"], entries),
                      "transitions": [transition]}
        elif active is not None:
            if transition["row"] != active["row"]:
                raise AssertionError("Selected row changed during playback")
            expected_phase = (2, 3, 0)[len(active["transitions"]) - 1]
            if phase != expected_phase:
                raise AssertionError(f"Playback expected phase {expected_phase}, observed {phase}")
            active["transitions"].append(transition)
            if phase == 0:
                if transition["completed_row"] != active["row"]:
                    raise AssertionError("Return did not retain the completed row")
                request, playing, finish, returned = active["transitions"]
                if not request["frame"] < playing["frame"] < finish["frame"] < returned["frame"]:
                    raise AssertionError("Native request, playback, finish and return frames must advance")
                active.update({
                    "request_frame": request["frame"], "play_frame": playing["frame"],
                    "finish_frame": finish["frame"], "return_frame": returned["frame"],
                    "elapsed_frames": returned["frame"] - request["frame"],
                    "playback_frames": finish["frame"] - playing["frame"],
                })
                runs.append(active)
                active = None
        elif phase != 0:
            raise AssertionError(f"Phase {phase} was observed without a native selection request")

    shots = {}
    observation_keys = [(x["frame"], x["line"], x["result_index"]) for x in observations]
    all_runs = runs + ([active] if active else [])
    latest_paths = {capture["path"]: index for index, capture in enumerate(captures)}
    for index, capture in enumerate(captures):
        shot = dict(capture)
        key = Path(shot["path"]).name
        if key in shots:
            key += f"#{index + 1}"
        shot["original_filename"] = Path(shot["path"]).name
        shot["capture_index"] = index
        shot["file_overwritten_by_later_capture"] = latest_paths[shot["path"]] != index
        position = bisect_right(observation_keys, (shot["frame"], shot["line"], shot["result_index"])) - 1
        # A read-only initial watch established later in the same stopped guest
        # frame also identifies an earlier screenshot taken in that frame.
        if position < 0 and observations[0]["frame"] == shot["frame"]:
            position = 0
        shot.update({"stage": "not_observed", "scene": None,
                     "last_completed_scene": None, "run_index": None})
        if position >= 0:
            state = observations[position]
            phase = state["phase"]
            shot.update({"stage": STAGES[phase], "native_phase": phase,
                         "native_state_row": state["row"],
                         "native_completed_row": state["completed_row"],
                         "state_observed_frame": state["frame"],
                         "state_watch_line": state["line"]})
            if phase:
                shot["scene"] = _scene(state["row"], entries)
                matching = [run for run in all_runs if run["row"] == state["row"]
                            and run["transitions"][0]["frame"] <= shot["frame"]
                            and ("return_frame" not in run or shot["frame"] < run["return_frame"])]
                if matching:
                    shot["run_index"] = matching[-1]["run_index"]
            else:
                completed = [run for run in runs if run["return_frame"] <= shot["frame"]]
                if completed:
                    last = completed[-1]
                    if last["row"] != state["completed_row"]:
                        raise AssertionError("List screenshot state differs from the last completed run")
                    shot["last_completed_scene"] = _scene(last["row"], entries)
                    shot["last_completed_run_index"] = last["run_index"]
        name = shot["scene"]["name"] if shot["scene"] else None
        if name:
            shot["display_label"] = f"{name} / {shot['stage']} / frame {shot['frame']}"
        elif shot["last_completed_scene"]:
            shot["display_label"] = (
                f"播放器空闲 / 上次完成：{shot['last_completed_scene']['name']} / frame {shot['frame']}"
            )
        else:
            shot["display_label"] = f"{shot['stage']} / frame {shot['frame']}"
        claim = re.match(r"^(play|returned)-(\d+)(?:\D|$)", shot["original_filename"])
        if claim and position >= 0:
            claimed_phase = "playing" if claim[1] == "play" else "gallery_idle"
            claimed_row = int(claim[2])
            actual = shot["scene"] if phase else shot["last_completed_scene"]
            shot["filename_matches_observed_state"] = (
                shot["stage"] == claimed_phase and actual is not None and actual["row"] == claimed_row
            )
        shots[key] = shot

    completed_rows = {run["row"] for run in runs}
    missing = [_scene(row, entries) for row in range(len(entries)) if row not in completed_rows]
    complete = not missing and active is None
    result = {
        "evidence_type": "LRPS2 recorded native UI flow",
        "journal": str(journal.resolve()),
        "journal_sha256": hashlib.sha256(journal_bytes).hexdigest(),
        "configured_scenes": len(entries),
        "completed_runs": len(runs), "runs": runs, "screenshots": shots,
        "missing_scenes": missing, "pending_run": active,
        "all_scenes_completed_and_returned": complete,
        "natural_completion_without_host_state_intervention": complete,
        "boundary": (
            "WATCH proves the request/play/finish/return state chain and retained completed row. "
            "Phase zero indicates an idle gallery player; it does not distinguish the list "
            "from the theater root after leaving the list. Native row is the last played item, "
            "not the current UI highlight. "
            "Screenshot filenames are not scene evidence. Cold-start provenance, original list "
            "object identity, visual fidelity and PCSX2 manual acceptance require separate evidence."
        ),
    }
    if require_complete and not complete:
        description = ", ".join(f"{x['row']}:{x['name']}" for x in missing) or "none"
        pending = f"; active row {active['row']} phase {active['transitions'][-1]['phase']}" if active else ""
        raise AssertionError(f"Gallery coverage incomplete; missing completed rows {description}{pending}")
    return result


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("journal", type=Path)
    parser.add_argument("--config", type=Path, default=root / "config/products/special-disc/event-gallery.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-incomplete", action="store_true",
                        help="Write an honest partial report while the live test is still running")
    args = parser.parse_args()
    result = verify(args.journal, json.loads(args.config.read_text())["entries"],
                    require_complete=not args.allow_incomplete)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    if result["all_scenes_completed_and_returned"]:
        print(f"Verified {result['completed_runs']} complete runs covering all {result['configured_scenes']} scenes")
    else:
        print(f"Partial evidence: {result['completed_runs']} complete runs; "
              f"{len(result['missing_scenes'])} configured scenes still lack completion")
