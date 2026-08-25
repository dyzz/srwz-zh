from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
import zlib
from datetime import datetime, timezone
from pathlib import Path

from tools.srwz.lrps2_runtime import (
    InputAction,
    Lrps2RuntimeError,
    append_input_sequences,
    crop_rgba,
    dhash_distance,
    dhash_rgba,
    encode_png_rgba,
    input_schedule,
    load_common_sequence_registry,
    load_scenario,
    make_input_factory,
    mean_luma_rgba,
    resolve_session_output_directory,
    unwrap_pointer_value,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FakeJoypadState:
    def __init__(self, **buttons: bool):
        self.buttons = buttons


class FakePointer:
    def __init__(self, value):
        self.value = value


class Lrps2RuntimeTest(unittest.TestCase):
    def test_common_sequence_registry_matches_tracked_scenarios(self) -> None:
        registry = load_common_sequence_registry(
            PROJECT_ROOT / "config" / "runtime" / "lrps2-common-sequences.json"
        )
        self.assertEqual(
            list(registry),
            ["title", "new-game", "load", "continue", "library"],
        )
        self.assertEqual(registry["load"]["buttons"], ("start", "down", "circle"))
        self.assertEqual(registry["load"]["scenario_id"], "load-menu")

    def test_custom_sequence_appends_relative_buttons_and_capture(self) -> None:
        scenario = load_scenario(
            PROJECT_ROOT / "config" / "runtime" / "lrps2-title.json"
        )
        composed, metadata = append_input_sequences(
            scenario,
            [
                PROJECT_ROOT
                / "config"
                / "runtime"
                / "examples"
                / "lrps2-custom-open-load.json"
            ],
            PROJECT_ROOT,
        )
        self.assertEqual(composed.scenario_id, "title--custom-open-load")
        self.assertEqual(
            [
                (action.frame, action.button, action.duration_frames)
                for action in composed.actions
            ],
            [(1801, "start", 3), (1981, "down", 3), (2041, "circle", 3)],
        )
        self.assertEqual(composed.terminal_frame, 2220)
        self.assertEqual(
            [(capture.capture_id, capture.frame) for capture in composed.captures],
            [("title-main-menu", 1920), ("custom-populated-load-list", 2220)],
        )
        self.assertEqual(metadata[0]["start_after_frame"], 1920)
        self.assertEqual(metadata[0]["action_count"], 2)
        self.assertEqual(metadata[0]["capture_count"], 1)
        self.assertRegex(metadata[0]["sha256"], r"^[0-9a-f]{64}$")

    def test_custom_sequence_requires_buttons_and_capture_evidence(self) -> None:
        scenario = load_scenario(
            PROJECT_ROOT / "config" / "runtime" / "lrps2-title.json"
        )
        invalid = {
            "schema_version": 1,
            "sequence_id": "missing-capture",
            "description": "Invalid test sequence.",
            "steps": [
                {
                    "after_frames": 60,
                    "button": "circle",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertRaisesRegex(Lrps2RuntimeError, "no capture steps"):
                append_input_sequences(scenario, [path], PROJECT_ROOT)

    def test_all_title_routes_are_tracked(self) -> None:
        expected_routes = {
            "title": [(1801, "start")],
            "new-game-menu": [(1801, "start"), (2041, "circle")],
            "load-menu": [
                (1801, "start"),
                (1981, "down"),
                (2041, "circle"),
            ],
            "continue-menu": [
                (1801, "start"),
                (1981, "down"),
                (2041, "down"),
                (2101, "circle"),
            ],
            "library-menu": [
                (1801, "start"),
                (1981, "down"),
                (2041, "down"),
                (2101, "down"),
                (2161, "circle"),
            ],
        }
        for scenario_id, expected_actions in expected_routes.items():
            with self.subTest(scenario_id=scenario_id):
                scenario = load_scenario(
                    PROJECT_ROOT / "config" / "runtime" / f"lrps2-{scenario_id}.json"
                )
                self.assertEqual(scenario.scenario_id, scenario_id)
                self.assertEqual(
                    [(action.frame, action.button) for action in scenario.actions],
                    expected_actions,
                )
                self.assertTrue(scenario.captures)
                self.assertTrue(
                    all(capture.expected_width == 640 for capture in scenario.captures)
                )
                self.assertTrue(
                    all(capture.expected_height == 448 for capture in scenario.captures)
                )

    def test_tracked_load_menu_scenario_uses_current_armsx2_card(self) -> None:
        scenario = load_scenario(
            PROJECT_ROOT / "config" / "runtime" / "lrps2-load-menu.json"
        )
        self.assertEqual(scenario.scenario_id, "load-menu")
        self.assertEqual(scenario.required_machine, "x86_64")
        self.assertEqual(scenario.libretro_py_version, "0.8.3")
        self.assertEqual(
            scenario.memory_card_path,
            "~/Library/Application Support/ARMSX2/memcards/Mcd001.ps2",
        )
        self.assertIsNone(scenario.memory_card_sha256)
        self.assertEqual(
            [
                (action.frame, action.button, action.duration_frames)
                for action in scenario.actions
            ],
            [(1801, "start", 3), (1981, "down", 3), (2041, "circle", 3)],
        )
        self.assertEqual(scenario.terminal_frame, 2220)
        self.assertEqual(
            [capture.capture_id for capture in scenario.captures],
            [
                "title-load-selected",
                "memory-card-check-complete",
                "populated-load-list",
            ],
        )
        self.assertEqual(
            [capture.expected_dhash for capture in scenario.captures],
            [
                "c22f2b82a30dab55",
                "1803232b0b43414d",
                "0058780880304846",
            ],
        )
        self.assertEqual(scenario.captures[-1].dhash_region, (0, 0, 640, 70))

    def test_input_schedule_uses_lrps2_face_button_mapping(self) -> None:
        actions = (
            InputAction(2, "circle", 2, "confirm"),
            InputAction(5, "cross", 1, "cancel"),
        )
        schedule = input_schedule(actions, 5)
        self.assertEqual(
            schedule,
            (
                frozenset(),
                frozenset({"a"}),
                frozenset({"a"}),
                frozenset(),
                frozenset({"b"}),
            ),
        )
        states = list(make_input_factory(actions, 5, FakeJoypadState)())
        self.assertEqual(states[1].buttons, {"a": True})
        self.assertEqual(states[4].buttons, {"b": True})

    def test_rgba_metrics_and_png_are_dependency_free(self) -> None:
        width = 9
        height = 8
        pixels = bytearray()
        for _y in range(height):
            for x in range(width):
                value = x * 20
                pixels.extend((value, value, value, 255))
        rgba = bytes(pixels)
        self.assertGreater(mean_luma_rgba(rgba, width, height), 0)
        self.assertEqual(dhash_rgba(rgba, width, height), "0000000000000000")
        png = encode_png_rgba(rgba, width, height)
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertIn(b"IHDR", png)
        self.assertIn(b"IEND", png)
        self.assertGreater(len(zlib.compress(rgba)), 0)

    def test_rgba_crop_is_exact_and_bounds_checked(self) -> None:
        rgba = bytes(range(4 * 4 * 4))
        cropped, width, height = crop_rgba(rgba, 4, 4, (1, 1, 2, 2))
        self.assertEqual((width, height), (2, 2))
        self.assertEqual(cropped, rgba[20:28] + rgba[36:44])
        with self.assertRaisesRegex(Lrps2RuntimeError, "exceeds"):
            crop_rgba(rgba, 4, 4, (3, 3, 2, 2))

    def test_session_output_is_fail_closed_under_gitignored_work(self) -> None:
        started_at = datetime(2026, 8, 24, 12, 34, 56, tzinfo=timezone.utc)
        output = resolve_session_output_directory(
            PROJECT_ROOT,
            "load-menu",
            started_at=started_at,
            process_id=123,
        )
        self.assertEqual(
            output,
            PROJECT_ROOT
            / "work"
            / "runtime"
            / "lrps2"
            / "load-menu"
            / "20260824T123456Z-123",
        )
        relative = resolve_session_output_directory(
            PROJECT_ROOT,
            "load-menu",
            Path("work/runtime/lrps2/custom/session"),
        )
        self.assertEqual(
            relative,
            PROJECT_ROOT / "work" / "runtime" / "lrps2" / "custom" / "session",
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(Lrps2RuntimeError, "must be a child"):
                resolve_session_output_directory(
                    PROJECT_ROOT,
                    "load-menu",
                    Path(directory) / "escaped-session",
                )
        ignored = subprocess.run(
            [
                "git",
                "check-ignore",
                "--quiet",
                "work/runtime/lrps2/load-menu/test-session/receipt.json",
            ],
            cwd=PROJECT_ROOT,
            check=False,
        )
        self.assertEqual(ignored.returncode, 0)

    def test_dhash_distance_and_nested_pointer_unwrap(self) -> None:
        self.assertEqual(
            dhash_distance("0000000000000000", "000000000000000f"),
            4,
        )
        nested = FakePointer(FakePointer(0x1234))
        self.assertEqual(unwrap_pointer_value(nested, (FakePointer,)), 0x1234)

    def test_scenario_rejects_overlapping_actions(self) -> None:
        scenario = json.loads(
            (PROJECT_ROOT / "config" / "runtime" / "lrps2-load-menu.json").read_text(
                encoding="utf-8"
            )
        )
        scenario["actions"][1]["frame"] = 1802
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scenario.json"
            path.write_text(json.dumps(scenario), encoding="utf-8")
            with self.assertRaisesRegex(Lrps2RuntimeError, "overlap"):
                load_scenario(path)


if __name__ == "__main__":
    unittest.main()
