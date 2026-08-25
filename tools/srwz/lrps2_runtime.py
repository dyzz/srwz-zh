"""Deterministic LRPS2/libretro.py runtime-validation primitives."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import re
import shutil
import struct
import zlib
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
from typing import Callable, Iterator, Mapping, Sequence


HASH_CHUNK_SIZE = 4 * 1024 * 1024
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
DHASH_PATTERN = re.compile(r"^[0-9a-f]{16}$")

# LRPS2 exposes PS2 face buttons through the RetroPad layout.  The names on
# the left are the player-facing PS2 names used by scenario files.
BUTTON_FIELDS = {
    "cross": "b",
    "circle": "a",
    "triangle": "x",
    "square": "y",
    "start": "start",
    "select": "select",
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
    "l1": "l",
    "r1": "r",
    "l2": "l2",
    "r2": "r2",
    "l3": "l3",
    "r3": "r3",
}


class Lrps2RuntimeError(RuntimeError):
    """An LRPS2 runtime contract or assertion failed."""


@dataclass(frozen=True)
class InputAction:
    """One one-based, frame-timed controller pulse."""

    frame: int
    button: str
    duration_frames: int
    label: str

    @property
    def final_frame(self) -> int:
        return self.frame + self.duration_frames - 1


@dataclass(frozen=True)
class CaptureSpec:
    """Screenshot and optional visual assertions for one completed frame."""

    capture_id: str
    frame: int
    expected_width: int | None = None
    expected_height: int | None = None
    min_mean_luma: float | None = None
    max_mean_luma: float | None = None
    expected_dhash: str | None = None
    max_dhash_distance: int = 0
    dhash_region: tuple[int, int, int, int] | None = None


@dataclass(frozen=True)
class RuntimeScenario:
    """Validated, dependency-free representation of an LRPS2 scenario."""

    scenario_id: str
    description: str
    required_system: str
    required_machine: str
    minimum_python: tuple[int, int]
    libretro_py_version: str
    core_path: str
    core_sha256: str
    system_directory: str
    iso_build_config: str
    memory_card_path: str
    memory_card_sha256: str | None
    core_options: Mapping[str, str]
    actions: tuple[InputAction, ...]
    captures: tuple[CaptureSpec, ...]
    terminal_frame: int


def sha256_file(path: Path) -> tuple[int, str]:
    """Return a file's size and SHA-256 without loading it into memory."""

    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(HASH_CHUNK_SIZE):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _require_mapping(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise Lrps2RuntimeError(f"{label} must be an object")
    return value


def _require_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise Lrps2RuntimeError(f"{label} must be a non-empty string")
    return value


def _require_positive_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise Lrps2RuntimeError(f"{label} must be a positive integer")
    return value


def _require_nonnegative_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise Lrps2RuntimeError(f"{label} must be a non-negative integer")
    return value


def _optional_number(value: object, label: str) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise Lrps2RuntimeError(f"{label} must be numeric")
    result = float(value)
    if not 0 <= result <= 255:
        raise Lrps2RuntimeError(f"{label} must be in the range 0..255")
    return result


def _parse_minimum_python(value: object) -> tuple[int, int]:
    text = _require_string(value, "environment.minimum_python")
    match = re.fullmatch(r"(\d+)\.(\d+)", text)
    if not match:
        raise Lrps2RuntimeError("environment.minimum_python must look like '3.12'")
    return int(match.group(1)), int(match.group(2))


def _parse_capture_spec(
    capture_data: dict,
    label: str,
    *,
    frame: int | None = None,
) -> CaptureSpec:
    capture_id = _require_string(capture_data.get("id"), f"{label}.id")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", capture_id):
        raise Lrps2RuntimeError(f"{label}.id must use lowercase kebab-case")
    if frame is None:
        frame = _require_positive_int(capture_data.get("frame"), f"{label}.frame")
    expected_width = capture_data.get("expected_width")
    expected_height = capture_data.get("expected_height")
    if expected_width is not None:
        expected_width = _require_positive_int(
            expected_width, f"{label}.expected_width"
        )
    if expected_height is not None:
        expected_height = _require_positive_int(
            expected_height, f"{label}.expected_height"
        )
    expected_dhash = capture_data.get("expected_dhash")
    if expected_dhash is not None:
        expected_dhash = _require_string(expected_dhash, f"{label}.expected_dhash")
        if not DHASH_PATTERN.fullmatch(expected_dhash):
            raise Lrps2RuntimeError(
                f"{label}.expected_dhash must be 16 lowercase hex digits"
            )
    max_distance = capture_data.get("max_dhash_distance", 0)
    if not isinstance(max_distance, int) or isinstance(max_distance, bool):
        raise Lrps2RuntimeError(f"{label}.max_dhash_distance must be an integer")
    if not 0 <= max_distance <= 64:
        raise Lrps2RuntimeError(
            f"{label}.max_dhash_distance must be in the range 0..64"
        )
    dhash_region_data = capture_data.get("dhash_region")
    dhash_region = None
    if dhash_region_data is not None:
        region = _require_mapping(dhash_region_data, f"{label}.dhash_region")
        dhash_region = (
            _require_nonnegative_int(region.get("x"), f"{label}.dhash_region.x"),
            _require_nonnegative_int(region.get("y"), f"{label}.dhash_region.y"),
            _require_positive_int(region.get("width"), f"{label}.dhash_region.width"),
            _require_positive_int(region.get("height"), f"{label}.dhash_region.height"),
        )
    return CaptureSpec(
        capture_id=capture_id,
        frame=frame,
        expected_width=expected_width,
        expected_height=expected_height,
        min_mean_luma=_optional_number(
            capture_data.get("min_mean_luma"),
            f"{label}.min_mean_luma",
        ),
        max_mean_luma=_optional_number(
            capture_data.get("max_mean_luma"),
            f"{label}.max_mean_luma",
        ),
        expected_dhash=expected_dhash,
        max_dhash_distance=max_distance,
        dhash_region=dhash_region,
    )


def load_scenario(path: Path) -> RuntimeScenario:
    """Load and fail-closed validate a tracked LRPS2 scenario."""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Lrps2RuntimeError(f"could not load scenario {path}: {exc}") from exc
    root = _require_mapping(raw, "scenario")
    if root.get("schema_version") != 1:
        raise Lrps2RuntimeError("scenario.schema_version must be 1")

    scenario_id = _require_string(root.get("scenario_id"), "scenario_id")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", scenario_id):
        raise Lrps2RuntimeError("scenario_id must use lowercase kebab-case")
    terminal_frame = _require_positive_int(root.get("terminal_frame"), "terminal_frame")

    environment = _require_mapping(root.get("environment"), "environment")
    core = _require_mapping(environment.get("core"), "environment.core")
    core_sha256 = _require_string(core.get("sha256"), "environment.core.sha256")
    if not SHA256_PATTERN.fullmatch(core_sha256):
        raise Lrps2RuntimeError("environment.core.sha256 is not SHA-256")

    iso = _require_mapping(root.get("iso"), "iso")
    memory_card = _require_mapping(root.get("memory_card"), "memory_card")
    memory_card_sha256 = memory_card.get("sha256")
    if memory_card_sha256 is not None:
        memory_card_sha256 = _require_string(memory_card_sha256, "memory_card.sha256")
        if not SHA256_PATTERN.fullmatch(memory_card_sha256):
            raise Lrps2RuntimeError("memory_card.sha256 is not SHA-256")

    core_options = _require_mapping(root.get("core_options"), "core_options")
    if not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in core_options.items()
    ):
        raise Lrps2RuntimeError("core_options keys and values must be strings")

    raw_actions = root.get("actions")
    if not isinstance(raw_actions, list) or not raw_actions:
        raise Lrps2RuntimeError("actions must be a non-empty array")
    actions = []
    occupied_frames: dict[int, str] = {}
    for index, raw_action in enumerate(raw_actions):
        label = f"actions[{index}]"
        action_data = _require_mapping(raw_action, label)
        frame = _require_positive_int(action_data.get("frame"), f"{label}.frame")
        duration = _require_positive_int(
            action_data.get("duration_frames"), f"{label}.duration_frames"
        )
        button = _require_string(action_data.get("button"), f"{label}.button").lower()
        if button not in BUTTON_FIELDS:
            raise Lrps2RuntimeError(f"{label}.button is unsupported: {button!r}")
        action = InputAction(
            frame=frame,
            button=button,
            duration_frames=duration,
            label=_require_string(action_data.get("label"), f"{label}.label"),
        )
        if action.final_frame > terminal_frame:
            raise Lrps2RuntimeError(f"{label} extends past terminal_frame")
        for active_frame in range(action.frame, action.final_frame + 1):
            previous = occupied_frames.get(active_frame)
            if previous is not None:
                raise Lrps2RuntimeError(
                    f"input actions overlap at frame {active_frame}: "
                    f"{previous!r} and {action.label!r}"
                )
            occupied_frames[active_frame] = action.label
        actions.append(action)

    raw_captures = root.get("captures")
    if not isinstance(raw_captures, list) or not raw_captures:
        raise Lrps2RuntimeError("captures must be a non-empty array")
    captures = []
    capture_ids = set()
    capture_frames = set()
    for index, raw_capture in enumerate(raw_captures):
        label = f"captures[{index}]"
        capture_data = _require_mapping(raw_capture, label)
        capture = _parse_capture_spec(capture_data, label)
        if capture.capture_id in capture_ids:
            raise Lrps2RuntimeError(f"duplicate capture id: {capture.capture_id}")
        capture_ids.add(capture.capture_id)
        if capture.frame > terminal_frame:
            raise Lrps2RuntimeError(f"{label}.frame exceeds terminal_frame")
        if capture.frame in capture_frames:
            raise Lrps2RuntimeError(f"duplicate capture frame: {capture.frame}")
        capture_frames.add(capture.frame)
        captures.append(capture)

    return RuntimeScenario(
        scenario_id=scenario_id,
        description=_require_string(root.get("description"), "description"),
        required_system=_require_string(
            environment.get("required_system"), "environment.required_system"
        ),
        required_machine=_require_string(
            environment.get("required_machine"), "environment.required_machine"
        ),
        minimum_python=_parse_minimum_python(environment.get("minimum_python")),
        libretro_py_version=_require_string(
            environment.get("libretro_py_version"),
            "environment.libretro_py_version",
        ),
        core_path=_require_string(core.get("path"), "environment.core.path"),
        core_sha256=core_sha256,
        system_directory=_require_string(
            environment.get("system_directory"),
            "environment.system_directory",
        ),
        iso_build_config=_require_string(iso.get("build_config"), "iso.build_config"),
        memory_card_path=_require_string(memory_card.get("path"), "memory_card.path"),
        memory_card_sha256=memory_card_sha256,
        core_options=dict(core_options),
        actions=tuple(actions),
        captures=tuple(captures),
        terminal_frame=terminal_frame,
    )


def load_common_sequence_registry(path: Path) -> dict[str, dict]:
    """Load named common routes and verify their declared button sequences."""

    path = path.resolve()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Lrps2RuntimeError(
            f"could not load common sequence registry {path}: {exc}"
        ) from exc
    root = _require_mapping(raw, "common sequence registry")
    if root.get("schema_version") != 1:
        raise Lrps2RuntimeError("common sequence registry schema_version must be 1")
    entries = _require_mapping(root.get("sequences"), "sequences")
    if not entries:
        raise Lrps2RuntimeError("common sequence registry must not be empty")

    result = {}
    for name, raw_entry in entries.items():
        if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name):
            raise Lrps2RuntimeError(
                f"common sequence name must use lowercase kebab-case: {name!r}"
            )
        label = f"sequences.{name}"
        entry = _require_mapping(raw_entry, label)
        scenario_value = _require_string(entry.get("scenario"), f"{label}.scenario")
        scenario_path = Path(scenario_value).expanduser()
        if not scenario_path.is_absolute():
            scenario_path = path.parent / scenario_path
        scenario_path = scenario_path.resolve()
        scenario = load_scenario(scenario_path)
        raw_buttons = entry.get("buttons")
        if not isinstance(raw_buttons, list) or not raw_buttons:
            raise Lrps2RuntimeError(f"{label}.buttons must be a non-empty array")
        buttons = []
        for index, raw_button in enumerate(raw_buttons):
            button = _require_string(raw_button, f"{label}.buttons[{index}]").lower()
            if button not in BUTTON_FIELDS:
                raise Lrps2RuntimeError(
                    f"{label}.buttons[{index}] is unsupported: {button!r}"
                )
            buttons.append(button)
        actual_buttons = [action.button for action in scenario.actions]
        if buttons != actual_buttons:
            raise Lrps2RuntimeError(
                f"{label}.buttons {buttons!r} do not match scenario actions "
                f"{actual_buttons!r}"
            )
        result[name] = {
            "name": name,
            "description": _require_string(
                entry.get("description"), f"{label}.description"
            ),
            "scenario_id": scenario.scenario_id,
            "scenario_path": scenario_path,
            "buttons": tuple(buttons),
            "terminal_frame": scenario.terminal_frame,
        }
    return result


def append_input_sequences(
    scenario: RuntimeScenario,
    sequence_paths: Sequence[Path],
    project_root: Path,
) -> tuple[RuntimeScenario, tuple[dict, ...]]:
    """Append relative, frame-timed custom input/capture sequences to a route."""

    project_root = project_root.resolve()
    actions = list(scenario.actions)
    captures = list(scenario.captures)
    capture_ids = {capture.capture_id for capture in captures}
    metadata = []

    for raw_path in sequence_paths:
        path = _resolve_path(project_root, raw_path)
        try:
            payload = path.read_bytes()
            raw = json.loads(payload.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise Lrps2RuntimeError(
                f"could not load custom input sequence {path}: {exc}"
            ) from exc
        root = _require_mapping(raw, "custom input sequence")
        if root.get("schema_version") != 1:
            raise Lrps2RuntimeError(
                f"custom input sequence {path} schema_version must be 1"
            )
        sequence_id = _require_string(root.get("sequence_id"), "sequence_id")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", sequence_id):
            raise Lrps2RuntimeError("sequence_id must use lowercase kebab-case")
        description = _require_string(root.get("description"), "description")
        raw_steps = root.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            raise Lrps2RuntimeError("custom input sequence steps must be non-empty")

        start_frame = scenario.terminal_frame
        cursor = start_frame
        action_count = 0
        capture_count = 0
        for index, raw_step in enumerate(raw_steps):
            label = f"steps[{index}]"
            step = _require_mapping(raw_step, label)
            after_frames = _require_positive_int(
                step.get("after_frames"), f"{label}.after_frames"
            )
            event_frame = cursor + after_frames
            has_button = "button" in step
            has_capture = "capture" in step
            if has_button == has_capture:
                raise Lrps2RuntimeError(
                    f"{label} must contain exactly one of button or capture"
                )
            if has_button:
                button = _require_string(step.get("button"), f"{label}.button").lower()
                if button not in BUTTON_FIELDS:
                    raise Lrps2RuntimeError(
                        f"{label}.button is unsupported: {button!r}"
                    )
                duration = _require_positive_int(
                    step.get("duration_frames", 3), f"{label}.duration_frames"
                )
                action = InputAction(
                    frame=event_frame,
                    button=button,
                    duration_frames=duration,
                    label=_require_string(
                        step.get(
                            "label",
                            f"{sequence_id}-step-{index + 1}-{button}",
                        ),
                        f"{label}.label",
                    ),
                )
                actions.append(action)
                cursor = action.final_frame
                action_count += 1
            else:
                capture_data = _require_mapping(step.get("capture"), f"{label}.capture")
                if "frame" in capture_data:
                    raise Lrps2RuntimeError(
                        f"{label}.capture.frame is not allowed; use after_frames"
                    )
                capture = _parse_capture_spec(
                    capture_data,
                    f"{label}.capture",
                    frame=event_frame,
                )
                if capture.capture_id in capture_ids:
                    raise Lrps2RuntimeError(
                        f"duplicate capture id: {capture.capture_id}"
                    )
                capture_ids.add(capture.capture_id)
                captures.append(capture)
                cursor = capture.frame
                capture_count += 1

        if not action_count:
            raise Lrps2RuntimeError(
                f"custom input sequence {sequence_id!r} has no button steps"
            )
        if not capture_count:
            raise Lrps2RuntimeError(
                f"custom input sequence {sequence_id!r} has no capture steps"
            )
        composite_id = f"{scenario.scenario_id}--{sequence_id}"
        if len(composite_id) > 160:
            raise Lrps2RuntimeError("composed scenario_id exceeds 160 characters")
        scenario = replace(
            scenario,
            scenario_id=composite_id,
            description=f"{scenario.description} {description}",
            actions=tuple(actions),
            captures=tuple(captures),
            terminal_frame=cursor,
        )
        metadata.append(
            {
                "sequence_id": sequence_id,
                "description": description,
                "path": str(path),
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "start_after_frame": start_frame,
                "terminal_frame": cursor,
                "action_count": action_count,
                "capture_count": capture_count,
            }
        )

    return scenario, tuple(metadata)


def input_schedule(
    actions: Sequence[InputAction],
    terminal_frame: int,
) -> tuple[frozenset[str], ...]:
    """Expand input actions to one set of JoypadState fields per frame."""

    schedule = [set() for _ in range(terminal_frame)]
    for action in actions:
        field = BUTTON_FIELDS[action.button]
        for frame in range(action.frame, action.final_frame + 1):
            schedule[frame - 1].add(field)
    return tuple(frozenset(fields) for fields in schedule)


def make_input_factory(
    actions: Sequence[InputAction],
    terminal_frame: int,
    joypad_state_type: Callable[..., object],
) -> Callable[[], Iterator[object]]:
    """Return a generator function accepted by libretro.py Session(input=...)."""

    schedule = input_schedule(actions, terminal_frame)

    def generate() -> Iterator[object]:
        for active_fields in schedule:
            yield joypad_state_type(**{field: True for field in active_fields})

    return generate


def _luma(red: int, green: int, blue: int) -> int:
    return (77 * red + 150 * green + 29 * blue) >> 8


def mean_luma_rgba(data: bytes, width: int, height: int) -> float:
    """Return the mean 8-bit luma of a packed RGBA image."""

    expected = width * height * 4
    if len(data) != expected:
        raise Lrps2RuntimeError(
            f"RGBA buffer has {len(data)} bytes, expected {expected}"
        )
    if not width or not height:
        raise Lrps2RuntimeError("RGBA dimensions must be non-zero")
    total = 0
    for offset in range(0, len(data), 4):
        total += _luma(data[offset], data[offset + 1], data[offset + 2])
    return total / (width * height)


def dhash_rgba(data: bytes, width: int, height: int) -> str:
    """Return a deterministic 64-bit difference hash for packed RGBA pixels."""

    expected = width * height * 4
    if len(data) != expected:
        raise Lrps2RuntimeError(
            f"RGBA buffer has {len(data)} bytes, expected {expected}"
        )
    if width < 9 or height < 8:
        raise Lrps2RuntimeError("dHash requires an image of at least 9x8 pixels")

    samples = []
    for row in range(8):
        y0 = row * height // 8
        y1 = (row + 1) * height // 8
        sample_row = []
        for column in range(9):
            x0 = column * width // 9
            x1 = (column + 1) * width // 9
            total = 0
            count = 0
            for y in range(y0, y1):
                offset = (y * width + x0) * 4
                for _x in range(x0, x1):
                    total += _luma(data[offset], data[offset + 1], data[offset + 2])
                    count += 1
                    offset += 4
            sample_row.append(total // count)
        samples.append(sample_row)

    value = 0
    for row in samples:
        for left, right in zip(row, row[1:]):
            value = (value << 1) | int(left > right)
    return f"{value:016x}"


def crop_rgba(
    data: bytes,
    width: int,
    height: int,
    region: tuple[int, int, int, int],
) -> tuple[bytes, int, int]:
    """Crop a packed RGBA image to ``(x, y, width, height)``."""

    expected = width * height * 4
    if len(data) != expected:
        raise Lrps2RuntimeError(
            f"RGBA buffer has {len(data)} bytes, expected {expected}"
        )
    x, y, crop_width, crop_height = region
    if x < 0 or y < 0 or crop_width <= 0 or crop_height <= 0:
        raise Lrps2RuntimeError("RGBA crop region is invalid")
    if x + crop_width > width or y + crop_height > height:
        raise Lrps2RuntimeError(
            f"RGBA crop region {region!r} exceeds {width}x{height} framebuffer"
        )
    stride = width * 4
    row_size = crop_width * 4
    cropped = b"".join(
        data[(row * stride) + (x * 4) : (row * stride) + (x * 4) + row_size]
        for row in range(y, y + crop_height)
    )
    return cropped, crop_width, crop_height


def dhash_distance(left: str, right: str) -> int:
    """Return the Hamming distance between two validated 64-bit dHashes."""

    if not DHASH_PATTERN.fullmatch(left) or not DHASH_PATTERN.fullmatch(right):
        raise Lrps2RuntimeError("dHash values must be 16 lowercase hex digits")
    return bin(int(left, 16) ^ int(right, 16)).count("1")


def encode_png_rgba(data: bytes, width: int, height: int) -> bytes:
    """Encode packed RGBA pixels as a deterministic, dependency-free PNG."""

    expected = width * height * 4
    if len(data) != expected:
        raise Lrps2RuntimeError(
            f"RGBA buffer has {len(data)} bytes, expected {expected}"
        )
    if not width or not height:
        raise Lrps2RuntimeError("PNG dimensions must be non-zero")

    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return (
            struct.pack(">I", len(payload))
            + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    stride = width * 4
    scanlines = b"".join(
        b"\0" + data[offset : offset + stride] for offset in range(0, len(data), stride)
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(
            b"IHDR",
            struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0),
        )
        + chunk(b"IDAT", zlib.compress(scanlines, level=9))
        + chunk(b"IEND", b"")
    )


def unwrap_pointer_value(value: object, pointer_types: tuple[type, ...]) -> object:
    """Unwrap libretro.py's nested c_void_ptr values without guessing addresses."""

    for _ in range(8):
        if not isinstance(value, pointer_types):
            return value
        value = value.value
    raise Lrps2RuntimeError("framebuffer pointer nesting is unexpectedly deep")


def install_libretro_video_pointer_compatibility() -> None:
    """Install the libretro.py 0.8.3 nested-framebuffer-pointer workaround."""

    import ctypes

    from libretro.api._utils import MAX_POINTER_VALUE, memoryview_at
    from libretro.ctypes import c_void_ptr
    from libretro.drivers.environment.composite import CompositeEnvironmentDriver
    from libretro.drivers.environment.driver import EnvironmentDriver
    from libretro.drivers.video.driver import FrameBufferSpecial

    if getattr(CompositeEnvironmentDriver.video_refresh, "_srwz_compat", False):
        return

    @EnvironmentDriver.return_on_raise(None)
    def compatible_video_refresh(self, data, width, height, pitch):
        value = unwrap_pointer_value(data.value, (c_void_ptr, ctypes.c_void_p))
        if value in (None, 0):
            self._video.refresh(FrameBufferSpecial.DUPE, width, height, pitch)
        elif value == MAX_POINTER_VALUE:
            self._video.refresh(FrameBufferSpecial.HARDWARE, width, height, pitch)
        elif isinstance(value, int):
            view = memoryview_at(value, pitch * height, readonly=True)
            if len(view) != pitch * height:
                raise Lrps2RuntimeError(
                    f"framebuffer has {len(view)} bytes, expected {pitch * height}"
                )
            self._video.refresh(view, width, height, pitch)
        else:
            raise Lrps2RuntimeError(f"unsupported framebuffer pointer value: {value!r}")

    compatible_video_refresh._srwz_compat = True
    CompositeEnvironmentDriver.video_refresh = compatible_video_refresh


def _resolve_path(project_root: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = project_root / path
    return path.resolve()


def resolve_session_output_directory(
    project_root: Path,
    scenario_id: str,
    output_directory: Path | None = None,
    *,
    started_at: datetime | None = None,
    process_id: int | None = None,
) -> Path:
    """Resolve a session path and reject anything outside ignored ``work/``."""

    project_root = project_root.resolve()
    session_root = (project_root / "work" / "runtime" / "lrps2").resolve()
    if output_directory is None:
        timestamp = (started_at or datetime.now(timezone.utc)).strftime(
            "%Y%m%dT%H%M%SZ"
        )
        candidate = (
            session_root
            / scenario_id
            / f"{timestamp}-{process_id if process_id is not None else os.getpid()}"
        )
    else:
        candidate = Path(output_directory).expanduser()
        if not candidate.is_absolute():
            candidate = project_root / candidate
        candidate = candidate.resolve()
    if candidate == session_root or not candidate.is_relative_to(session_root):
        raise Lrps2RuntimeError(
            f"LRPS2 session output must be a child of {session_root}; got {candidate}"
        )
    return candidate


def _load_iso_contract(project_root: Path, config_value: str) -> dict:
    config_path = _resolve_path(project_root, config_value)
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        output = config["output"]
        iso_path = _resolve_path(project_root, output["path"])
        expected_size = output["expected_size"]
        expected_sha256 = output["expected_sha256"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise Lrps2RuntimeError(
            f"could not read ISO output contract from {config_path}: {exc}"
        ) from exc
    if not isinstance(expected_size, int) or expected_size <= 0:
        raise Lrps2RuntimeError("ISO expected_size is invalid")
    if not isinstance(expected_sha256, str) or not SHA256_PATTERN.fullmatch(
        expected_sha256
    ):
        raise Lrps2RuntimeError("ISO expected_sha256 is invalid")
    return {
        "config": config_path,
        "path": iso_path,
        "expected_size": expected_size,
        "expected_sha256": expected_sha256,
    }


def _decode_bytes(value: bytes | None) -> str | None:
    return value.decode("utf-8", errors="replace") if value is not None else None


def run_validation(
    *,
    project_root: Path,
    scenario_path: Path,
    core_override: Path | None = None,
    core_sha256_override: str | None = None,
    system_directory_override: Path | None = None,
    iso_override: Path | None = None,
    iso_sha256_override: str | None = None,
    memory_card_override: Path | None = None,
    memory_card_sha256_override: str | None = None,
    custom_input_sequence_paths: Sequence[Path] = (),
    output_directory: Path | None = None,
) -> dict:
    """Run one pinned LRPS2 scenario and write local screenshots plus receipt."""

    project_root = project_root.resolve()
    scenario_path = scenario_path.resolve()
    scenario_size, scenario_sha256 = sha256_file(scenario_path)
    scenario = load_scenario(scenario_path)
    base_scenario_id = scenario.scenario_id
    scenario, custom_sequence_metadata = append_input_sequences(
        scenario,
        custom_input_sequence_paths,
        project_root,
    )
    started_at = datetime.now(timezone.utc)
    output_directory = resolve_session_output_directory(
        project_root,
        scenario.scenario_id,
        output_directory,
        started_at=started_at,
    )
    output_directory.mkdir(parents=True, exist_ok=False)
    frames_directory = output_directory / "frames"
    frames_directory.mkdir()
    receipt_path = output_directory / "receipt.json"

    receipt = {
        "schema_version": 1,
        "scenario_id": scenario.scenario_id,
        "base_scenario": {
            "scenario_id": base_scenario_id,
            "path": str(scenario_path),
            "size": scenario_size,
            "sha256": scenario_sha256,
        },
        "description": scenario.description,
        "status": "running",
        "started_at": started_at.isoformat(),
        "output_directory": str(output_directory),
        "environment": {
            "system": platform.system(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "core_options": dict(scenario.core_options),
        "custom_input_sequences": list(custom_sequence_metadata),
        "input_actions": [
            {
                "frame": action.frame,
                "button": action.button,
                "duration_frames": action.duration_frames,
                "label": action.label,
            }
            for action in scenario.actions
        ],
        "captures": [],
    }

    source_card_path: Path | None = None
    isolated_card_path: Path | None = None
    source_card_hash_before: str | None = None
    failure: Exception | None = None
    try:
        if platform.system() != scenario.required_system:
            raise Lrps2RuntimeError(
                f"scenario requires {scenario.required_system}, got {platform.system()}"
            )
        if platform.machine() != scenario.required_machine:
            raise Lrps2RuntimeError(
                f"scenario requires {scenario.required_machine}; run it with an "
                f"x86_64 Python under Rosetta, got {platform.machine()}"
            )
        current_python = tuple(
            int(value) for value in platform.python_version_tuple()[:2]
        )
        if current_python < scenario.minimum_python:
            raise Lrps2RuntimeError(
                f"scenario requires Python {scenario.minimum_python[0]}."
                f"{scenario.minimum_python[1]}+"
            )

        core_path = (
            core_override.resolve()
            if core_override is not None
            else _resolve_path(project_root, scenario.core_path)
        )
        if not core_path.is_file():
            raise Lrps2RuntimeError(f"missing LRPS2 core: {core_path}")
        core_size, core_hash = sha256_file(core_path)
        expected_core_hash = core_sha256_override or scenario.core_sha256
        if not SHA256_PATTERN.fullmatch(expected_core_hash):
            raise Lrps2RuntimeError("expected core SHA-256 is invalid")
        if core_hash != expected_core_hash:
            raise Lrps2RuntimeError(
                f"LRPS2 core SHA-256 {core_hash}, expected {expected_core_hash}"
            )
        receipt["core"] = {
            "path": str(core_path),
            "size": core_size,
            "sha256": core_hash,
        }

        system_directory = (
            system_directory_override.resolve()
            if system_directory_override is not None
            else _resolve_path(project_root, scenario.system_directory)
        )
        bios_directory = system_directory / "pcsx2" / "bios"
        bios_files = (
            [path for path in bios_directory.iterdir() if path.is_file()]
            if bios_directory.is_dir()
            else []
        )
        if not bios_files:
            raise Lrps2RuntimeError(f"no BIOS files found under {bios_directory}")
        receipt["system_directory"] = {
            "path": str(system_directory),
            "bios_file_count": len(bios_files),
        }

        iso_contract = _load_iso_contract(project_root, scenario.iso_build_config)
        iso_path = (
            iso_override.resolve() if iso_override is not None else iso_contract["path"]
        )
        expected_iso_hash = iso_sha256_override or iso_contract["expected_sha256"]
        if not SHA256_PATTERN.fullmatch(expected_iso_hash):
            raise Lrps2RuntimeError("expected ISO SHA-256 is invalid")
        if not iso_path.is_file():
            raise Lrps2RuntimeError(f"missing ISO: {iso_path}")
        iso_size, iso_hash = sha256_file(iso_path)
        if iso_size != iso_contract["expected_size"]:
            raise Lrps2RuntimeError(
                f"ISO size {iso_size}, expected {iso_contract['expected_size']}"
            )
        if iso_hash != expected_iso_hash:
            raise Lrps2RuntimeError(
                f"ISO SHA-256 {iso_hash}, expected {expected_iso_hash}"
            )
        receipt["iso"] = {
            "path": str(iso_path),
            "size": iso_size,
            "sha256": iso_hash,
            "build_config": str(iso_contract["config"]),
        }

        source_card_path = (
            memory_card_override.resolve()
            if memory_card_override is not None
            else _resolve_path(project_root, scenario.memory_card_path)
        )
        if not source_card_path.is_file():
            raise Lrps2RuntimeError(f"missing memory card: {source_card_path}")
        card_size, source_card_hash_before = sha256_file(source_card_path)
        expected_card_hash = (
            memory_card_sha256_override
            if memory_card_sha256_override is not None
            else scenario.memory_card_sha256
        )
        if expected_card_hash is not None and not SHA256_PATTERN.fullmatch(
            expected_card_hash
        ):
            raise Lrps2RuntimeError("expected memory-card SHA-256 is invalid")
        if (
            expected_card_hash is not None
            and source_card_hash_before != expected_card_hash
        ):
            raise Lrps2RuntimeError(
                f"memory-card SHA-256 {source_card_hash_before}, "
                f"expected {expected_card_hash}"
            )
        save_directory = output_directory / "save"
        save_directory.mkdir()
        isolated_card_path = save_directory / f"{iso_path.stem}.ps2"
        shutil.copy2(source_card_path, isolated_card_path)
        isolated_size_before, isolated_hash_before = sha256_file(isolated_card_path)
        if (
            isolated_size_before != card_size
            or isolated_hash_before != source_card_hash_before
        ):
            raise Lrps2RuntimeError(
                "isolated memory-card copy does not match the ARMSX2 source"
            )
        receipt["memory_card"] = {
            "source_path": str(source_card_path),
            "source_size": card_size,
            "source_sha256": source_card_hash_before,
            "expected_sha256": expected_card_hash,
            "isolated_path": str(isolated_card_path),
            "isolated_size_before": isolated_size_before,
            "isolated_sha256_before": isolated_hash_before,
            "copy_verified": True,
        }

        try:
            installed_libretro_version = package_version("libretro.py")
        except PackageNotFoundError as exc:
            raise Lrps2RuntimeError(
                "libretro.py is not installed in this Python environment"
            ) from exc
        if installed_libretro_version != scenario.libretro_py_version:
            raise Lrps2RuntimeError(
                f"libretro.py {installed_libretro_version}, expected "
                f"{scenario.libretro_py_version}"
            )
        receipt["environment"]["libretro_py"] = installed_libretro_version

        install_libretro_video_pointer_compatibility()
        from libretro import Core, Session
        from libretro.api.input import JoypadState
        from libretro.drivers.path import ExplicitPathDriver
        from libretro.drivers.video import ArrayVideoDriver

        core = Core(core_path)
        core_info = core.get_system_info()
        receipt["core"].update(
            {
                "library_name": _decode_bytes(core_info.library_name),
                "library_version": _decode_bytes(core_info.library_version),
                "valid_extensions": _decode_bytes(core_info.valid_extensions),
                "need_fullpath": bool(core_info.need_fullpath),
            }
        )
        video = ArrayVideoDriver()
        core_logger = logging.Logger(f"srwz.lrps2.{os.getpid()}")
        core_logger.addHandler(logging.NullHandler())
        core_logger.propagate = False
        paths = ExplicitPathDriver(
            corepath=core_path,
            system=system_directory,
            save=save_directory,
        )
        input_factory = make_input_factory(
            scenario.actions,
            scenario.terminal_frame,
            JoypadState,
        )
        captures_by_frame = {capture.frame: capture for capture in scenario.captures}

        with Session(
            core,
            iso_path,
            input=input_factory,
            video=video,
            path=paths,
            options=dict(scenario.core_options),
            # LRPS2 currently expects the log interface to exist during
            # retro_init.  Supply it but discard verbose core messages.
            log=core_logger,
        ) as session:
            for frame in range(1, scenario.terminal_frame + 1):
                session.run()
                capture = captures_by_frame.get(frame)
                if capture is None:
                    continue
                screenshot = video.screenshot()
                if screenshot is None or not screenshot.width or not screenshot.height:
                    raise Lrps2RuntimeError(
                        f"capture {capture.capture_id} at frame {frame} has no framebuffer"
                    )
                rgba = bytes(screenshot.data)
                luma = mean_luma_rgba(rgba, screenshot.width, screenshot.height)
                dhash = dhash_rgba(rgba, screenshot.width, screenshot.height)
                assertion_rgba = rgba
                assertion_width = screenshot.width
                assertion_height = screenshot.height
                if capture.dhash_region is not None:
                    (
                        assertion_rgba,
                        assertion_width,
                        assertion_height,
                    ) = crop_rgba(
                        rgba,
                        screenshot.width,
                        screenshot.height,
                        capture.dhash_region,
                    )
                assertion_dhash = dhash_rgba(
                    assertion_rgba,
                    assertion_width,
                    assertion_height,
                )
                png = encode_png_rgba(rgba, screenshot.width, screenshot.height)
                png_path = frames_directory / (f"{frame:05d}-{capture.capture_id}.png")
                png_path.write_bytes(png)
                capture_receipt = {
                    "id": capture.capture_id,
                    "frame": frame,
                    "path": str(png_path),
                    "width": screenshot.width,
                    "height": screenshot.height,
                    "pixel_format": screenshot.pixel_format.name,
                    "mean_luma": round(luma, 6),
                    "dhash": dhash,
                    "dhash_region": (
                        {
                            "x": capture.dhash_region[0],
                            "y": capture.dhash_region[1],
                            "width": capture.dhash_region[2],
                            "height": capture.dhash_region[3],
                        }
                        if capture.dhash_region is not None
                        else None
                    ),
                    "assertion_dhash": assertion_dhash,
                    "rgba_sha256": hashlib.sha256(rgba).hexdigest(),
                    "png_sha256": hashlib.sha256(png).hexdigest(),
                    "assertions": [],
                }

                def assert_capture(
                    condition: bool, assertion: str, detail: str
                ) -> None:
                    capture_receipt["assertions"].append(
                        {"assertion": assertion, "passed": condition, "detail": detail}
                    )
                    if not condition:
                        receipt["captures"].append(capture_receipt)
                        raise Lrps2RuntimeError(
                            f"capture {capture.capture_id} failed {assertion}: {detail}"
                        )

                if capture.expected_width is not None:
                    assert_capture(
                        screenshot.width == capture.expected_width,
                        "expected_width",
                        f"actual={screenshot.width} expected={capture.expected_width}",
                    )
                if capture.expected_height is not None:
                    assert_capture(
                        screenshot.height == capture.expected_height,
                        "expected_height",
                        f"actual={screenshot.height} expected={capture.expected_height}",
                    )
                if capture.min_mean_luma is not None:
                    assert_capture(
                        luma >= capture.min_mean_luma,
                        "min_mean_luma",
                        f"actual={luma:.6f} minimum={capture.min_mean_luma}",
                    )
                if capture.max_mean_luma is not None:
                    assert_capture(
                        luma <= capture.max_mean_luma,
                        "max_mean_luma",
                        f"actual={luma:.6f} maximum={capture.max_mean_luma}",
                    )
                if capture.expected_dhash is not None:
                    distance = dhash_distance(assertion_dhash, capture.expected_dhash)
                    assert_capture(
                        distance <= capture.max_dhash_distance,
                        "dhash_distance",
                        f"actual={assertion_dhash} expected={capture.expected_dhash} "
                        f"distance={distance} maximum={capture.max_dhash_distance}",
                    )
                receipt["captures"].append(capture_receipt)

        if source_card_path is None or source_card_hash_before is None:
            raise Lrps2RuntimeError("memory-card source was not initialized")
        _source_size_after, source_hash_after = sha256_file(source_card_path)
        receipt["memory_card"]["source_sha256_after"] = source_hash_after
        receipt["memory_card"]["source_unchanged"] = (
            source_card_hash_before == source_hash_after
        )
        if source_hash_after != source_card_hash_before:
            raise Lrps2RuntimeError(
                "ARMSX2 source memory card changed during LRPS2 validation"
            )
        receipt["status"] = "passed"
    except Exception as exc:
        failure = exc
        receipt["status"] = "failed"
        receipt["failure"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
    finally:
        if source_card_path is not None and source_card_path.is_file():
            _size, source_hash_after = sha256_file(source_card_path)
            receipt.setdefault("memory_card", {})["source_sha256_after"] = (
                source_hash_after
            )
            receipt["memory_card"]["source_unchanged"] = (
                source_card_hash_before == source_hash_after
            )
        if isolated_card_path is not None and isolated_card_path.is_file():
            isolated_size, isolated_hash = sha256_file(isolated_card_path)
            receipt.setdefault("memory_card", {})["isolated_size_after"] = isolated_size
            receipt["memory_card"]["isolated_sha256_after"] = isolated_hash
        receipt["finished_at"] = datetime.now(timezone.utc).isoformat()
        receipt_path.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    if failure is not None:
        raise failure
    return receipt


__all__ = [
    "BUTTON_FIELDS",
    "CaptureSpec",
    "InputAction",
    "Lrps2RuntimeError",
    "RuntimeScenario",
    "append_input_sequences",
    "crop_rgba",
    "dhash_distance",
    "dhash_rgba",
    "encode_png_rgba",
    "input_schedule",
    "install_libretro_video_pointer_compatibility",
    "load_scenario",
    "load_common_sequence_registry",
    "make_input_factory",
    "mean_luma_rgba",
    "resolve_session_output_directory",
    "run_validation",
    "sha256_file",
    "unwrap_pointer_value",
]
