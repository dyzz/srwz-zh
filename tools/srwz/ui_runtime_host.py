"""Build a fail-closed host preflight for SRWZ UI runtime cases."""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

from .ui_runtime_matrix import audit_ui_runtime_matrix


class UiRuntimeHostError(ValueError):
    """The local PCSX2 runtime host cannot be inspected safely."""


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
        raise UiRuntimeHostError(
            f"cannot inspect PCSX2 architectures: {path}"
        ) from error
    architectures = tuple(result.stdout.strip().split())
    if not architectures:
        raise UiRuntimeHostError(
            f"PCSX2 architecture inspection returned no values: {path}"
        )
    return architectures


def rosetta_available() -> bool:
    """Return whether this host can spawn an x86_64 process."""

    if platform.machine() != "arm64":
        return True
    try:
        result = subprocess.run(
            ["arch", "-x86_64", "/usr/bin/true"],
            check=False,
            capture_output=True,
        )
    except OSError:
        return False
    return result.returncode == 0


def build_runtime_host_preflight(
    project_root: Path,
    matrix_path: Path,
    pcsx2_path: Path,
    *,
    host_architecture: str,
    binary_architectures: tuple[str, ...],
    has_rosetta: bool,
    pine_socket_path: Path,
    artifact_id: str | None = None,
) -> dict:
    """Combine the reviewed matrix with explicit local host observations."""

    project_root = project_root.resolve()
    matrix_path = matrix_path.resolve()
    pcsx2_path = pcsx2_path.resolve()
    report = audit_ui_runtime_matrix(project_root, matrix_path)
    required_emulator = report["evidence_policy"]["required_emulator"]
    required_architecture = required_emulator["architecture"]
    all_ready_cases = tuple(
        case
        for case in report["cases"]
        if case["execution_readiness"] == "route_ready_runtime_not_tested"
    )
    ready_artifact_ids = {case["artifact_id"] for case in all_ready_cases}
    if artifact_id is None and len(ready_artifact_ids) != 1:
        raise UiRuntimeHostError(
            "route-ready cases bind multiple artifacts; select artifact_id"
        )
    if artifact_id is None:
        artifact_id = next(iter(ready_artifact_ids))
    elif artifact_id not in ready_artifact_ids:
        raise UiRuntimeHostError(
            f"selected artifact has no route-ready cases: {artifact_id}"
        )
    ready_cases = tuple(
        case
        for case in all_ready_cases
        if case["artifact_id"] == artifact_id
    )
    artifact = next(
        item
        for item in report["artifacts"]
        if item["artifact_id"] == artifact_id
    )

    binary_exists = pcsx2_path.is_file()
    binary_executable = binary_exists and os.access(pcsx2_path, os.X_OK)
    architecture_supported = required_architecture in binary_architectures
    translation_required = (
        host_architecture == "arm64" and required_architecture == "x86_64"
    )
    blockers = []
    if not binary_exists:
        blockers.append("pcsx2_binary_missing")
    elif not binary_executable:
        blockers.append("pcsx2_binary_not_executable")
    if binary_exists and not architecture_supported:
        blockers.append("pcsx2_architecture_mismatch")
    if translation_required and not has_rosetta:
        blockers.append("rosetta_missing")

    safe_to_launch = not blockers
    return {
        "schema_version": 1,
        "status": (
            "runtime_host_ready"
            if safe_to_launch
            else "runtime_host_blocked"
        ),
        "matrix": {
            "matrix_id": report["matrix_id"],
            "config": report["matrix_config"],
            "plan_sha256": report["matrix_plan_sha256"],
        },
        "ready_cases": {
            "count": len(ready_cases),
            "case_ids": [case["case_id"] for case in ready_cases],
            "artifact_id": artifact_id,
        },
        "artifact": {
            "iso_path": artifact["iso_path"],
            "iso_size": artifact["iso_size"],
            "iso_sha256": artifact["iso_sha256"],
        },
        "host": {
            "architecture": host_architecture,
            "pcsx2": {
                "path": str(pcsx2_path),
                "exists": binary_exists,
                "executable": binary_executable,
                "architectures": list(binary_architectures),
                "required_version": required_emulator["version"],
                "required_architecture": required_architecture,
                "architecture_supported": architecture_supported,
            },
            "translation": {
                "rosetta_required": translation_required,
                "rosetta_available": has_rosetta,
            },
            "pine": {
                "socket_path": str(pine_socket_path),
                "socket_exists_before_launch": pine_socket_path.exists(),
                "required_version": required_emulator["pine_version"],
            },
        },
        "launch": {
            "safe_to_launch": safe_to_launch,
            "blockers": blockers,
            "argv": [
                str(pcsx2_path),
                "-nogui",
                "-fastboot",
                "-nofullscreen",
                str(project_root / artifact["iso_path"]),
            ],
        },
        "runtime": {
            "status": "not_tested",
            "boundary": (
                "This preflight does not execute PCSX2 and cannot prove "
                "PINE, DVD, ELF, TLB or visual acceptance."
            ),
        },
    }
