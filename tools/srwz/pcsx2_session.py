"""Prepare hash-locked, isolated PCSX2 sessions for SRWZ runtime tests."""

from __future__ import annotations

import configparser
import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Callable, Mapping

class Pcsx2SessionError(ValueError):
    """A PCSX2 session or savestate lineage is unsafe or inconsistent."""


_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STATE_SUFFIX = ".p2s"
_MINIMUM_STATE_SIZE = 1024
_TARGET_GAME_ID = "SLPS-25887"
_PAGE_DATA_SIZE = 512
_PAGE_SPARE_SIZE = 16
_RAW_PAGE_SIZE = _PAGE_DATA_SIZE + _PAGE_SPARE_SIZE
_FORMAT_SIGNATURE = b"Sony PS2 Memory Card Format"
_TARGET_SAVE_MARKERS = (
    b"SLPS-25887",
    b"BISLPS-25887",
    b"SLPS_258.87",
    b"SLPS25887",
)


def pcsx2_architectures(path: Path) -> tuple[str, ...]:
    """Read Mach-O architectures without executing PCSX2."""

    if not path.is_file():
        return ()
    try:
        result = subprocess.run(
            ["/usr/bin/lipo", "-archs", str(path)],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise Pcsx2SessionError(
            f"cannot inspect PCSX2 architectures: {path}"
        ) from error
    architectures = tuple(result.stdout.strip().split())
    if not architectures:
        raise Pcsx2SessionError(
            f"PCSX2 architecture inspection returned no values: {path}"
        )
    return architectures


def inspect_memory_card(path: Path) -> dict:
    """Classify a PCSX2 memory-card image without modifying it."""

    path = path.resolve()
    raw = path.read_bytes()
    if raw and len(raw) % _RAW_PAGE_SIZE == 0:
        layout_name = "528-byte-pages"
        logical = b"".join(
            raw[offset : offset + _PAGE_DATA_SIZE]
            for offset in range(0, len(raw), _RAW_PAGE_SIZE)
        )
    elif raw and len(raw) % _PAGE_DATA_SIZE == 0:
        layout_name = "512-byte-pages"
        logical = raw
    else:
        layout_name = None
        logical = None

    all_ff = bool(raw) and all(value == 0xFF for value in raw)
    formatted = bool(logical) and logical.startswith(_FORMAT_SIGNATURE)
    marker_hits = (
        [
            marker.decode("ascii")
            for marker in _TARGET_SAVE_MARKERS
            if marker in logical
        ]
        if logical is not None
        else []
    )
    if all_ff:
        classification = "erased_unformatted"
    elif logical is None:
        classification = "unsupported_layout"
    elif formatted and marker_hits:
        classification = "formatted_target_save_candidate"
    elif formatted:
        classification = "formatted_no_target_marker"
    else:
        classification = "unrecognized_memory_card"
    return {
        "path": str(path),
        "size": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "layout": layout_name,
        "logical_size": len(logical) if logical is not None else None,
        "all_ff": all_ff,
        "formatted": formatted,
        "target_marker_hits": marker_hits,
        "classification": classification,
        "target_save_candidate": (
            classification == "formatted_target_save_candidate"
        ),
    }


def _case_workspace(project_root: Path, case_id: object) -> Path:
    if not isinstance(case_id, str) or not case_id:
        raise Pcsx2SessionError("runtime case_id is missing")
    relative = Path(case_id)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or any(
            _SAFE_SEGMENT.fullmatch(part) is None
            for part in relative.parts
        )
    ):
        raise Pcsx2SessionError("runtime case_id is not a safe relative path")
    return project_root / "work/runtime/ui-cases" / relative


def sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 for one file."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_object(path: Path, *, context: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise Pcsx2SessionError(f"cannot load {context} {path}: {error}") from error
    if not isinstance(value, dict):
        raise Pcsx2SessionError(f"{context} root must be an object: {path}")
    return value


def _safe_segment(value: str, *, context: str) -> str:
    if not isinstance(value, str) or _SAFE_SEGMENT.fullmatch(value) is None:
        raise Pcsx2SessionError(
            f"{context} must contain only letters, digits, dot, dash or underscore"
        )
    return value


def _project_relative(project_root: Path, path: Path, *, context: str) -> str:
    try:
        return str(path.resolve().relative_to(project_root.resolve()))
    except ValueError as error:
        raise Pcsx2SessionError(
            f"{context} must stay inside the project: {path}"
        ) from error


def _project_file(
    project_root: Path,
    raw: object,
    *,
    context: str,
    prefix: str | None = None,
) -> Path:
    if not isinstance(raw, str) or not raw:
        raise Pcsx2SessionError(f"{context} path is missing")
    relative = Path(raw)
    if relative.is_absolute() or ".." in relative.parts:
        raise Pcsx2SessionError(f"{context} path must be project-relative")
    if prefix is not None:
        try:
            relative.relative_to(prefix)
        except ValueError as error:
            raise Pcsx2SessionError(
                f"{context} path must be under {prefix}/"
            ) from error
    path = (project_root.resolve() / relative).resolve()
    try:
        path.relative_to(project_root.resolve())
    except ValueError as error:
        raise Pcsx2SessionError(f"{context} path escapes the project") from error
    if not path.is_file():
        raise Pcsx2SessionError(f"{context} file was not found: {relative}")
    return path


def _file_lock(
    project_root: Path,
    path: Path,
    *,
    context: str,
) -> dict:
    path = path.resolve()
    if not path.is_file():
        raise Pcsx2SessionError(f"{context} file was not found: {path}")
    return {
        "path": _project_relative(project_root, path, context=context),
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def inspect_pcsx2_app(
    app_path: Path,
    *,
    architecture_reader: Callable[[Path], tuple[str, ...]] = pcsx2_architectures,
) -> dict:
    """Inspect a PCSX2 bundle without executing the emulator."""

    app_path = app_path.expanduser().resolve()
    binary = app_path / "Contents/MacOS/PCSX2"
    info_path = app_path / "Contents/Info.plist"
    if not app_path.is_dir() or not binary.is_file() or not info_path.is_file():
        raise Pcsx2SessionError(f"invalid PCSX2 application bundle: {app_path}")
    if not os.access(binary, os.X_OK):
        raise Pcsx2SessionError(f"PCSX2 binary is not executable: {binary}")
    try:
        info = plistlib.loads(info_path.read_bytes())
    except (OSError, plistlib.InvalidFileException) as error:
        raise Pcsx2SessionError(
            f"cannot read PCSX2 Info.plist: {info_path}"
        ) from error
    raw_version = info.get("CFBundleShortVersionString")
    if not isinstance(raw_version, str) or not raw_version:
        raise Pcsx2SessionError("PCSX2 bundle does not declare a version")
    version = raw_version.removeprefix("v")
    architectures = architecture_reader(binary)
    return {
        "app_path": str(app_path),
        "version": version,
        "display_version": raw_version,
        "bundle_identifier": info.get("CFBundleIdentifier"),
        "binary_path": str(binary),
        "binary_size": binary.stat().st_size,
        "binary_sha256": sha256_file(binary),
        "architectures": list(architectures),
    }


def _copy_bundle(source: Path, destination: Path) -> None:
    """Clone a macOS app bundle when possible, then fall back to a real copy."""

    try:
        subprocess.run(
            ["/bin/cp", "-cR", str(source), str(destination)],
            check=True,
            capture_output=True,
        )
        return
    except (OSError, subprocess.CalledProcessError):
        pass
    try:
        shutil.copytree(source, destination, copy_function=shutil.copy2)
    except OSError as error:
        raise Pcsx2SessionError(
            f"cannot copy PCSX2 bundle to {destination}: {error}"
        ) from error


def _write_portable_settings(
    template_path: Path,
    output_path: Path,
    *,
    memory_card_enabled: bool,
) -> None:
    # PCSX2 writes list-style settings such as GameList/RecursivePaths more
    # than once.  Keep the last value while cloning a portable session rather
    # than rejecting the application's own valid settings file.
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    try:
        with template_path.open(encoding="utf-8") as stream:
            parser.read_file(stream)
    except (OSError, configparser.Error) as error:
        raise Pcsx2SessionError(
            f"cannot read PCSX2 settings template {template_path}: {error}"
        ) from error

    for section in ("Folders", "EmuCore", "MemoryCards"):
        if not parser.has_section(section):
            parser.add_section(section)
    folders = {
        "Bios": "bios",
        "Snapshots": "snaps",
        "Savestates": "sstates",
        "MemoryCards": "memcards",
        "Logs": "logs",
        "Cheats": "cheats",
        "Patches": "patches",
        "UserResources": "resources",
        "Cache": "cache",
        "Textures": "textures",
        "InputProfiles": "inputprofiles",
        "Videos": "videos",
        "DebuggerLayouts": "debuggerlayouts",
        "DebuggerSettings": "debuggersettings",
    }
    for key, value in folders.items():
        parser.set("Folders", key, value)
    parser.set("EmuCore", "EnablePINE", "true")
    parser.set("EmuCore", "SaveStateOnShutdown", "false")
    parser.set("EmuCore", "McdFolderAutoManage", "false")
    parser.set("MemoryCards", "Slot1_Enable", str(memory_card_enabled).lower())
    parser.set("MemoryCards", "Slot1_Filename", "Mcd001.ps2")
    parser.set("MemoryCards", "Slot2_Enable", "false")
    parser.set("MemoryCards", "Slot2_Filename", "Mcd002.ps2")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output_path.open("w", encoding="utf-8") as stream:
            parser.write(stream, space_around_delimiters=True)
    except OSError as error:
        raise Pcsx2SessionError(
            f"cannot write portable PCSX2 settings {output_path}: {error}"
        ) from error


def _artifact_lock(project_root: Path, case_plan: Mapping[str, object]) -> dict:
    artifact = case_plan.get("artifact")
    if not isinstance(artifact, Mapping):
        raise Pcsx2SessionError("runtime case plan does not contain an artifact")
    path = _project_file(
        project_root,
        artifact.get("iso_path"),
        context="runtime ISO",
        prefix="build/iso",
    )
    expected_size = artifact.get("iso_size")
    expected_sha256 = artifact.get("iso_sha256")
    if (
        not isinstance(expected_size, int)
        or isinstance(expected_size, bool)
        or expected_size <= 0
        or not isinstance(expected_sha256, str)
        or _SHA256.fullmatch(expected_sha256) is None
    ):
        raise Pcsx2SessionError("runtime case artifact lock is invalid")
    actual_size = path.stat().st_size
    actual_sha256 = sha256_file(path)
    if actual_size != expected_size or actual_sha256 != expected_sha256:
        raise Pcsx2SessionError("runtime ISO size or SHA-256 drift")
    return {
        "artifact_id": artifact.get("artifact_id"),
        "manifest": artifact.get("manifest"),
        "manifest_sha256": artifact.get("manifest_sha256"),
        "iso_path": _project_relative(
            project_root,
            path,
            context="runtime ISO",
        ),
        "iso_size": actual_size,
        "iso_sha256": actual_sha256,
    }


def with_exploratory_iso(
    project_root: Path,
    case_plan: Mapping[str, object],
    iso_path: Path,
) -> dict:
    """Return a copied case plan bound to an unpromoted exact local ISO."""

    project_root = project_root.resolve()
    iso_path = iso_path.expanduser().resolve()
    try:
        iso_relative = iso_path.relative_to(project_root / "build/iso")
    except ValueError as error:
        raise Pcsx2SessionError(
            "exploratory ISO must stay under build/iso/"
        ) from error
    if not iso_path.is_file():
        raise Pcsx2SessionError(
            f"exploratory ISO was not found: {iso_path}"
        )
    copied = deepcopy(dict(case_plan))
    original = copied.get("artifact")
    if not isinstance(original, Mapping):
        raise Pcsx2SessionError("runtime case plan artifact is invalid")
    copied["artifact"] = {
        "artifact_id": (
            f"exploratory-{original.get('artifact_id', 'unbound')}"
        ),
        "manifest": None,
        "manifest_sha256": None,
        "iso_path": str(Path("build/iso") / iso_relative),
        "iso_size": iso_path.stat().st_size,
        "iso_sha256": sha256_file(iso_path),
        "matrix_artifact_id": original.get("artifact_id"),
        "exploratory_override": True,
    }
    return copied


def _fixture_lock(
    project_root: Path,
    case_plan: Mapping[str, object],
    memory_card: Path | None,
    *,
    exploratory: bool,
) -> tuple[dict, Path | None, bool]:
    fixture = case_plan.get("fixture")
    if not isinstance(fixture, Mapping):
        raise Pcsx2SessionError("runtime case plan does not contain a fixture")
    fixture_kind = fixture.get("kind")
    fixture_status = fixture.get("status")
    fixture_id = fixture.get("fixture_id")

    if memory_card is None:
        if fixture_kind != "fresh_boot" or fixture_status != "ready":
            raise Pcsx2SessionError(
                "this runtime case requires an isolated memory card"
            )
        return (
            {
                "fixture_id": fixture_id,
                "kind": fixture_kind,
                "matrix_status": fixture_status,
                "source": None,
                "acceptance_eligible": True,
            },
            None,
            True,
        )

    memory_card = memory_card.expanduser().resolve()
    inspection = inspect_memory_card(memory_card)
    if not inspection["target_save_candidate"]:
        raise Pcsx2SessionError(
            "memory card is not a formatted SRWZ save candidate"
        )

    expected_sha256 = fixture.get("sha256")
    fixture_matches = (
        fixture_kind == "memory_card"
        and fixture_status == "ready"
        and isinstance(expected_sha256, str)
        and inspection["sha256"] == expected_sha256
    )
    if not fixture_matches and not exploratory:
        raise Pcsx2SessionError(
            "memory card is only an exploration candidate; use --exploratory"
        )
    return (
        {
            "fixture_id": fixture_id,
            "kind": fixture_kind,
            "matrix_status": fixture_status,
            "source": {
                "path": str(memory_card),
                "size": inspection["size"],
                "sha256": inspection["sha256"],
                "classification": inspection["classification"],
                "target_marker_hits": inspection["target_marker_hits"],
            },
            "acceptance_eligible": fixture_matches,
        },
        memory_card,
        fixture_matches,
    )


def _verify_locked_file(
    project_root: Path,
    lock: Mapping[str, object],
    *,
    context: str,
    prefix: str | None = None,
) -> Path:
    path = _project_file(
        project_root,
        lock.get("path"),
        context=context,
        prefix=prefix,
    )
    expected_size = lock.get("size")
    expected_sha256 = lock.get("sha256")
    if (
        path.stat().st_size != expected_size
        or sha256_file(path) != expected_sha256
    ):
        raise Pcsx2SessionError(f"{context} size or SHA-256 drift")
    return path


def verify_savestate_receipt(
    project_root: Path,
    receipt_path: Path,
) -> dict:
    """Verify a savestate, its card snapshot, ISO and emulator lineage."""

    project_root = project_root.resolve()
    receipt_path = receipt_path.resolve()
    receipt = _json_object(receipt_path, context="savestate receipt")
    if (
        receipt.get("schema_version") != 1
        or receipt.get("status") != "hash_locked_acceleration_only"
    ):
        raise Pcsx2SessionError("savestate receipt status is invalid")
    if receipt.get("acceptance_scope") != "acceleration_only":
        raise Pcsx2SessionError("savestate receipt cannot be primary evidence")

    session = receipt.get("source_session")
    artifact = receipt.get("artifact")
    emulator = receipt.get("emulator")
    state = receipt.get("savestate")
    card = receipt.get("memory_card_snapshot")
    if not all(
        isinstance(value, Mapping)
        for value in (session, artifact, emulator, state)
    ):
        raise Pcsx2SessionError("savestate receipt structure is invalid")
    _verify_locked_file(
        project_root,
        session,
        context="savestate source session lock",
        prefix="work/runtime/pcsx2-sessions",
    )
    _verify_locked_file(
        project_root,
        {
            "path": artifact.get("iso_path"),
            "size": artifact.get("iso_size"),
            "sha256": artifact.get("iso_sha256"),
        },
        context="savestate ISO",
        prefix="build/iso",
    )
    _verify_locked_file(
        project_root,
        state,
        context="savestate file",
        prefix="work/runtime/pcsx2-sessions",
    )
    if card is not None:
        if not isinstance(card, Mapping):
            raise Pcsx2SessionError("savestate memory-card snapshot is invalid")
        _verify_locked_file(
            project_root,
            card,
            context="savestate memory-card snapshot",
            prefix="work/runtime/pcsx2-sessions",
        )

    binary_path = Path(str(emulator.get("binary_path"))).expanduser().resolve()
    if (
        not binary_path.is_file()
        or binary_path.stat().st_size != emulator.get("binary_size")
        or sha256_file(binary_path) != emulator.get("binary_sha256")
    ):
        raise Pcsx2SessionError("savestate PCSX2 binary drift")
    return receipt


def _state_boot_inputs(
    project_root: Path,
    receipt_path: Path,
) -> tuple[dict, Path | None, Path]:
    receipt = verify_savestate_receipt(project_root, receipt_path)
    state = _project_file(
        project_root,
        receipt["savestate"]["path"],
        context="savestate file",
        prefix="work/runtime/pcsx2-sessions",
    )
    raw_card = receipt.get("memory_card_snapshot")
    card = None
    if raw_card is not None:
        card = _project_file(
            project_root,
            raw_card["path"],
            context="savestate memory-card snapshot",
            prefix="work/runtime/pcsx2-sessions",
        )
    return receipt, card, state


def prepare_pcsx2_session(
    project_root: Path,
    case_plan: Mapping[str, object],
    *,
    session_id: str,
    pcsx2_app: Path,
    settings_template: Path,
    bios_directory: Path,
    memory_card: Path | None = None,
    savestate_receipt: Path | None = None,
    exploratory: bool = False,
    architecture_reader: Callable[[Path], tuple[str, ...]] = pcsx2_architectures,
    bundle_copier: Callable[[Path, Path], None] = _copy_bundle,
) -> tuple[Path, Path]:
    """Create one isolated portable PCSX2 root and exact launch lock."""

    project_root = project_root.resolve()
    session_id = _safe_segment(session_id, context="session_id")
    if memory_card is not None and savestate_receipt is not None:
        raise Pcsx2SessionError(
            "memory card and savestate receipt are mutually exclusive"
        )

    workspace = (
        project_root / "work/runtime/pcsx2-sessions" / session_id
    ).resolve()
    try:
        workspace.relative_to(project_root / "work")
    except ValueError as error:
        raise Pcsx2SessionError("session workspace escapes work/") from error
    if workspace.exists():
        raise Pcsx2SessionError(f"session workspace already exists: {workspace}")

    artifact = _artifact_lock(project_root, case_plan)
    case = case_plan.get("case")
    if not isinstance(case, Mapping):
        raise Pcsx2SessionError("runtime case plan does not contain a case")
    emulator_requirement = case_plan.get("emulator")
    if not isinstance(emulator_requirement, Mapping):
        raise Pcsx2SessionError(
            "runtime case plan does not contain emulator requirements"
        )
    emulator = inspect_pcsx2_app(
        pcsx2_app,
        architecture_reader=architecture_reader,
    )
    required_version = emulator_requirement.get("version")
    required_architecture = emulator_requirement.get("architecture")
    if emulator["version"] != required_version:
        raise Pcsx2SessionError(
            f"PCSX2 version drift: {emulator['version']} != {required_version}"
        )
    if required_architecture not in emulator["architectures"]:
        raise Pcsx2SessionError("PCSX2 architecture does not match the matrix")

    state_source = None
    state_receipt_lock = None
    if savestate_receipt is not None:
        if not exploratory:
            raise Pcsx2SessionError(
                "savestate sessions must be explicitly exploratory"
            )
        receipt, card_source, state_source = _state_boot_inputs(
            project_root,
            savestate_receipt.resolve(),
        )
        if receipt["artifact"]["iso_sha256"] != artifact["iso_sha256"]:
            raise Pcsx2SessionError(
                "savestate was created from a different ISO"
            )
        if receipt["emulator"]["version"] != emulator["version"]:
            raise Pcsx2SessionError(
                "savestate was created by a different PCSX2 version"
            )
        if (
            receipt["emulator"]["binary_sha256"]
            != emulator["binary_sha256"]
        ):
            raise Pcsx2SessionError(
                "savestate was created by a different PCSX2 binary"
            )
        memory_card = card_source
        state_receipt_lock = _file_lock(
            project_root,
            savestate_receipt.resolve(),
            context="savestate receipt",
        )
        fixture = {
            "fixture_id": case_plan["fixture"]["fixture_id"],
            "kind": case_plan["fixture"]["kind"],
            "matrix_status": case_plan["fixture"]["status"],
            "source": receipt.get("memory_card_snapshot"),
            "acceptance_eligible": False,
        }
        primary_evidence_allowed = False
        boot_source = "savestate"
    else:
        fixture, memory_card, primary_evidence_allowed = _fixture_lock(
            project_root,
            case_plan,
            memory_card,
            exploratory=exploratory,
        )
        boot_source = (
            "memory_card" if memory_card is not None else "fresh_boot"
        )

    settings_template = settings_template.expanduser().resolve()
    bios_directory = bios_directory.expanduser().resolve()
    if not settings_template.is_file():
        raise Pcsx2SessionError(
            f"PCSX2 settings template was not found: {settings_template}"
        )
    if not bios_directory.is_dir():
        raise Pcsx2SessionError(
            f"PCSX2 BIOS directory was not found: {bios_directory}"
        )

    try:
        workspace.mkdir(parents=True)
        portable_app = workspace / "PCSX2.app"
        bundle_copier(pcsx2_app.resolve(), portable_app)
        for directory in (
            "cache",
            "cheats",
            "covers",
            "gamesettings",
            "inputprofiles",
            "logs",
            "memcards",
            "patches",
            "resources",
            "session-inputs",
            "snaps",
            "sstates",
            "textures",
            "videos",
            "inis/debuggerlayouts",
            "inis/debuggersettings",
        ):
            (workspace / directory).mkdir(parents=True, exist_ok=True)
        (workspace / "bios").symlink_to(bios_directory, target_is_directory=True)

        card_lock = None
        runtime_card_path = None
        if memory_card is not None:
            card_output = workspace / "session-inputs/Mcd001.ps2"
            runtime_card_path = workspace / "memcards/Mcd001.ps2"
            shutil.copy2(memory_card, card_output)
            shutil.copy2(card_output, runtime_card_path)
            card_lock = _file_lock(
                project_root,
                card_output,
                context="isolated memory-card baseline",
            )
            if sha256_file(memory_card) != card_lock["sha256"]:
                raise Pcsx2SessionError("isolated memory-card copy drift")

        state_lock = None
        state_output = None
        if state_source is not None:
            state_output = workspace / "session-inputs/boot-state.p2s"
            shutil.copy2(state_source, state_output)
            state_lock = _file_lock(
                project_root,
                state_output,
                context="isolated savestate",
            )
            if sha256_file(state_source) != state_lock["sha256"]:
                raise Pcsx2SessionError("isolated savestate copy drift")

        settings_output = workspace / "session-inputs/PCSX2.ini"
        _write_portable_settings(
            settings_template,
            settings_output,
            memory_card_enabled=card_lock is not None,
        )
        runtime_settings_path = workspace / "inis/PCSX2.ini"
        shutil.copy2(settings_output, runtime_settings_path)
        settings_lock = _file_lock(
            project_root,
            settings_output,
            context="portable PCSX2 settings baseline",
        )

        portable_binary = portable_app / "Contents/MacOS/PCSX2"
        portable_emulator = inspect_pcsx2_app(
            portable_app,
            architecture_reader=architecture_reader,
        )
        if (
            portable_emulator["version"] != emulator["version"]
            or portable_emulator["binary_sha256"]
            != emulator["binary_sha256"]
        ):
            raise Pcsx2SessionError("portable PCSX2 bundle copy drift")

        evidence_session_root = (
            _case_workspace(project_root, case["case_id"])
            / "sessions"
            / session_id
        )
        log_path = evidence_session_root / "logs/emulog.txt"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        argv = [
            str(portable_binary),
            "-portable",
            "-nogui",
            "-fastboot",
            "-nofullscreen",
            "-logfile",
            str(log_path),
        ]
        if state_output is not None:
            argv.extend(["-statefile", str(state_output)])
        argv.extend(["--", str(project_root / artifact["iso_path"])])

        lock = {
            "schema_version": 1,
            "status": "prepared_not_launched",
            "session_id": session_id,
            "case": {
                "case_id": case.get("case_id"),
                "purpose": case.get("purpose"),
                "route": case.get("route"),
                "assertions": case.get("assertions"),
            },
            "artifact": artifact,
            "fixture": fixture,
            "emulator": {
                "name": "PCSX2",
                "version": portable_emulator["version"],
                "architectures": portable_emulator["architectures"],
                "source_app_path": emulator["app_path"],
                "source_binary_sha256": emulator["binary_sha256"],
                "portable_binary": {
                    "path": _project_relative(
                        project_root,
                        portable_binary,
                        context="portable PCSX2 binary",
                    ),
                    "size": portable_binary.stat().st_size,
                    "sha256": sha256_file(portable_binary),
                },
            },
            "portable": {
                "root": _project_relative(
                    project_root,
                    workspace,
                    context="portable PCSX2 root",
                ),
                "settings": settings_lock,
                "runtime_settings_path": _project_relative(
                    project_root,
                    runtime_settings_path,
                    context="runtime PCSX2 settings",
                ),
                "bios_source": str(bios_directory),
                "memory_card": card_lock,
                "runtime_memory_card_path": (
                    _project_relative(
                        project_root,
                        runtime_card_path,
                        context="runtime memory card",
                    )
                    if runtime_card_path is not None
                    else None
                ),
                "savestate": state_lock,
                "savestate_receipt": state_receipt_lock,
            },
            "evidence_workspace": {
                "root": _project_relative(
                    project_root,
                    evidence_session_root,
                    context="case session evidence root",
                ),
            },
            "launch": {
                "boot_source": boot_source,
                "argv": argv,
                "cwd": str(project_root),
                "log_path": _project_relative(
                    project_root,
                    log_path,
                    context="PCSX2 log",
                ),
            },
            "evidence": {
                "exploratory": exploratory,
                "primary_runtime_receipt_allowed": (
                    primary_evidence_allowed and boot_source != "savestate"
                ),
                "savestate_policy": (
                    "Savestates are acceleration-only and are valid only "
                    "with this exact ISO, PCSX2 binary and card snapshot. "
                    "Primary acceptance starts from fresh boot or the "
                    "hash-locked native memory-card fixture."
                ),
            },
        }
        lock_path = workspace / "session-lock.json"
        launch_path = workspace / "launch.json"
        lock_path.write_text(
            json.dumps(lock, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        launch_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "session_lock": _file_lock(
                        project_root,
                        lock_path,
                        context="PCSX2 session lock",
                    ),
                    "argv": argv,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    except Exception:
        if workspace.exists():
            shutil.rmtree(workspace)
        raise
    return lock_path, launch_path


def validate_pcsx2_session(
    project_root: Path,
    lock_path: Path,
    *,
    allow_memory_card_drift: bool = False,
) -> dict:
    """Re-read every local input referenced by a prepared PCSX2 session."""

    project_root = project_root.resolve()
    lock_path = lock_path.resolve()
    lock = _json_object(lock_path, context="PCSX2 session lock")
    if (
        lock.get("schema_version") != 1
        or lock.get("status") != "prepared_not_launched"
    ):
        raise Pcsx2SessionError("PCSX2 session lock status is invalid")
    artifact = lock.get("artifact")
    emulator = lock.get("emulator")
    portable = lock.get("portable")
    launch = lock.get("launch")
    if not all(
        isinstance(value, Mapping)
        for value in (artifact, emulator, portable, launch)
    ):
        raise Pcsx2SessionError("PCSX2 session lock structure is invalid")
    _verify_locked_file(
        project_root,
        {
            "path": artifact.get("iso_path"),
            "size": artifact.get("iso_size"),
            "sha256": artifact.get("iso_sha256"),
        },
        context="PCSX2 session ISO",
        prefix="build/iso",
    )
    binary = _verify_locked_file(
        project_root,
        emulator.get("portable_binary"),
        context="portable PCSX2 binary",
        prefix="work/runtime/pcsx2-sessions",
    )
    _verify_locked_file(
        project_root,
        portable.get("settings"),
        context="portable PCSX2 settings baseline",
        prefix="work/runtime/pcsx2-sessions",
    )
    _project_file(
        project_root,
        portable.get("runtime_settings_path"),
        context="runtime PCSX2 settings",
        prefix="work/runtime/pcsx2-sessions",
    )
    card = portable.get("memory_card")
    if card is not None:
        if not isinstance(card, Mapping):
            raise Pcsx2SessionError("portable memory-card lock is invalid")
        baseline_card = _verify_locked_file(
            project_root,
            card,
            context="portable memory-card baseline",
            prefix="work/runtime/pcsx2-sessions",
        )
        runtime_card = _project_file(
            project_root,
            portable.get("runtime_memory_card_path"),
            context="runtime memory card",
            prefix="work/runtime/pcsx2-sessions",
        )
        if (
            not allow_memory_card_drift
            and (
                runtime_card.stat().st_size != baseline_card.stat().st_size
                or sha256_file(runtime_card) != sha256_file(baseline_card)
            )
        ):
            raise Pcsx2SessionError("runtime memory card drift")
    state = portable.get("savestate")
    if state is not None:
        if not isinstance(state, Mapping):
            raise Pcsx2SessionError("portable savestate lock is invalid")
        _verify_locked_file(
            project_root,
            state,
            context="portable savestate",
            prefix="work/runtime/pcsx2-sessions",
        )

    argv = launch.get("argv")
    if not isinstance(argv, list) or not all(
        isinstance(item, str) and item for item in argv
    ):
        raise Pcsx2SessionError("PCSX2 launch argv is invalid")
    if str(binary) != argv[0]:
        raise Pcsx2SessionError("PCSX2 launch binary drift")
    if launch.get("boot_source") == "savestate" and "-statefile" not in argv:
        raise Pcsx2SessionError("savestate session does not load a statefile")
    if launch.get("boot_source") != "savestate" and "-statefile" in argv:
        raise Pcsx2SessionError("non-savestate session unexpectedly loads a state")
    return lock


def register_pcsx2_savestate(
    project_root: Path,
    lock_path: Path,
    state_path: Path,
    *,
    state_id: str,
) -> Path:
    """Freeze one F1-created state and its current isolated card as a bundle."""

    project_root = project_root.resolve()
    lock_path = lock_path.resolve()
    state_id = _safe_segment(state_id, context="state_id")
    lock = validate_pcsx2_session(
        project_root,
        lock_path,
        allow_memory_card_drift=True,
    )
    if lock["launch"]["boot_source"] == "savestate":
        raise Pcsx2SessionError(
            "do not derive an accepted state lineage from another savestate"
        )

    workspace = (
        project_root / lock["portable"]["root"]
    ).resolve()
    state_path = state_path.resolve()
    try:
        state_path.relative_to(workspace / "sstates")
    except ValueError as error:
        raise Pcsx2SessionError(
            "savestate must be created inside this session's sstates/"
        ) from error
    if (
        not state_path.is_file()
        or state_path.suffix.lower() != _STATE_SUFFIX
        or state_path.stat().st_size < _MINIMUM_STATE_SIZE
    ):
        raise Pcsx2SessionError("savestate file is missing, tiny or not .p2s")

    bundle = workspace / "state-bundles" / state_id
    if bundle.exists():
        raise Pcsx2SessionError(f"savestate bundle already exists: {bundle}")
    bundle.mkdir(parents=True)
    frozen_state = bundle / "state.p2s"
    shutil.copy2(state_path, frozen_state)
    state_lock = _file_lock(
        project_root,
        frozen_state,
        context="frozen savestate",
    )
    if sha256_file(state_path) != state_lock["sha256"]:
        raise Pcsx2SessionError("frozen savestate copy drift")

    card_snapshot = None
    card_lock = lock["portable"].get("memory_card")
    if card_lock is not None:
        card_path = _project_file(
            project_root,
            lock["portable"]["runtime_memory_card_path"],
            context="session runtime memory card",
            prefix="work/runtime/pcsx2-sessions",
        )
        frozen_card = bundle / "Mcd001.ps2"
        shutil.copy2(card_path, frozen_card)
        card_snapshot = _file_lock(
            project_root,
            frozen_card,
            context="savestate memory-card snapshot",
        )

    source_session = _file_lock(
        project_root,
        lock_path,
        context="savestate source session lock",
    )
    source_binary = Path(lock["emulator"]["source_app_path"]) / (
        "Contents/MacOS/PCSX2"
    )
    receipt = {
        "schema_version": 1,
        "status": "hash_locked_acceleration_only",
        "state_id": state_id,
        "game_id": _TARGET_GAME_ID,
        "source_session": source_session,
        "case_id": lock["case"]["case_id"],
        "artifact": lock["artifact"],
        "emulator": {
            "version": lock["emulator"]["version"],
            "binary_path": str(source_binary.resolve()),
            "binary_size": source_binary.stat().st_size,
            "binary_sha256": sha256_file(source_binary),
        },
        "savestate": state_lock,
        "memory_card_snapshot": card_snapshot,
        "acceptance_scope": "acceleration_only",
        "reuse_requirements": [
            "Exact ISO SHA-256 match.",
            "Exact PCSX2 version and binary SHA-256 match.",
            "Use the bundled memory-card snapshot when present.",
            "Do not promote a missing native memory-card fixture from this state.",
            "Do not use a savestate-derived session as primary runtime evidence.",
        ],
    }
    receipt_path = bundle / "receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    verify_savestate_receipt(project_root, receipt_path)
    return receipt_path


def newest_session_savestate(session_root: Path) -> Path:
    """Return the newest indexed PCSX2 state in one isolated session."""

    candidates = [
        path
        for path in (session_root.resolve() / "sstates").glob("*.p2s")
        if path.is_file()
    ]
    if not candidates:
        raise Pcsx2SessionError("no .p2s file exists in this session")
    return max(candidates, key=lambda path: (path.stat().st_mtime_ns, path.name))


def collect_pcsx2_session(
    project_root: Path,
    lock_path: Path,
) -> Path:
    """Copy stable logs and screenshots into the case-owned evidence workspace."""

    project_root = project_root.resolve()
    lock_path = lock_path.resolve()
    lock = validate_pcsx2_session(
        project_root,
        lock_path,
        allow_memory_card_drift=True,
    )
    session_root = project_root / lock["portable"]["root"]
    source_log = project_root / lock["launch"]["log_path"]
    if not source_log.is_file() or source_log.stat().st_size == 0:
        raise Pcsx2SessionError("PCSX2 session log is missing or empty")

    process_path = session_root / "process.json"
    if process_path.is_file():
        process = _json_object(process_path, context="PCSX2 process record")
        pid = process.get("pid")
        if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                pass
            except PermissionError as error:
                raise Pcsx2SessionError(
                    "cannot inspect the recorded PCSX2 process"
                ) from error
            else:
                raise Pcsx2SessionError(
                    "stop PCSX2 before collecting stable evidence files"
                )

    target_root = (
        _case_workspace(project_root, lock["case"]["case_id"])
        / "collected"
        / lock["session_id"]
    )
    if target_root.exists():
        raise Pcsx2SessionError(
            f"session collection already exists: {target_root}"
        )
    logs_root = target_root / "logs"
    screenshots_root = target_root / "screenshots"
    logs_root.mkdir(parents=True)
    screenshots_root.mkdir()
    copied_log = logs_root / "emulog.txt"
    shutil.copy2(source_log, copied_log)
    screenshots = []
    for source in sorted((session_root / "snaps").glob("*.png")):
        if not source.is_file():
            continue
        target = screenshots_root / source.name
        shutil.copy2(source, target)
        screenshots.append(
            _file_lock(
                project_root,
                target,
                context="collected PCSX2 screenshot",
            )
        )
    report = {
        "schema_version": 1,
        "status": "collected_unreviewed",
        "session_lock": _file_lock(
            project_root,
            lock_path,
            context="collected PCSX2 session lock",
        ),
        "case_id": lock["case"]["case_id"],
        "session_id": lock["session_id"],
        "boot_source": lock["launch"]["boot_source"],
        "primary_runtime_receipt_allowed": lock["evidence"][
            "primary_runtime_receipt_allowed"
        ],
        "emulator_log": _file_lock(
            project_root,
            copied_log,
            context="collected PCSX2 log",
        ),
        "screenshots": screenshots,
        "boundary": (
            "Collection proves stable file hashes only. Screenshots and "
            "assertions still require review, and savestate sessions remain "
            "acceleration-only."
        ),
    }
    report_path = target_root / "collection.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report_path


__all__ = [
    "Pcsx2SessionError",
    "collect_pcsx2_session",
    "inspect_pcsx2_app",
    "newest_session_savestate",
    "prepare_pcsx2_session",
    "register_pcsx2_savestate",
    "sha256_file",
    "validate_pcsx2_session",
    "verify_savestate_receipt",
    "with_exploratory_iso",
]
