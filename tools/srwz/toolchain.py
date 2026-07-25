"""Pinned, source-only armips build and project-ASM verification."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Mapping, Sequence

from .patch_audit import PatchAuditError, audit_binary_patch


OFFICIAL_ARMIPS_REPOSITORY = "https://github.com/Kingcom/armips.git"
FORBIDDEN_EXECUTABLES = {
    "compresstool.exe",
    "mono",
    "srwz.dll",
    "srwz.exe",
    "wine",
    "wine64",
}


class ToolchainError(RuntimeError):
    """The pinned source, build or project output failed verification."""


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _checked_command(
    arguments: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    capture: bool = False,
) -> str:
    if not arguments:
        raise ToolchainError("empty command")
    executable = Path(arguments[0]).name.lower()
    if executable.endswith(".exe") or executable in FORBIDDEN_EXECUTABLES:
        raise ToolchainError(f"forbidden executable: {arguments[0]}")
    print(
        "$",
        " ".join(str(value) for value in arguments),
        flush=True,
    )
    try:
        result = subprocess.run(
            [str(value) for value in arguments],
            cwd=cwd,
            env=dict(env) if env is not None else None,
            check=True,
            text=True,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.STDOUT if capture else None,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        output = getattr(error, "stdout", None)
        detail = f"\n{output.rstrip()}" if output else ""
        raise ToolchainError(
            f"command failed: {' '.join(arguments)}{detail}"
        ) from error
    return result.stdout.strip() if capture else ""


def _git(path: Path, *arguments: str) -> str:
    return _checked_command(
        ("git", "-C", str(path), *arguments),
        capture=True,
    )


def _version_line(executable: str) -> str:
    output = _checked_command((executable, "--version"), capture=True)
    return output.splitlines()[0]


def _require_sha256(value, *, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9a-f]{64}",
        value,
    ):
        raise ToolchainError(f"{field} is not a lowercase SHA-256")
    return value


def _require_git_object(value, *, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9a-f]{40}",
        value,
    ):
        raise ToolchainError(f"{field} is not a full Git object id")
    return value


def _repo_path(project_root: Path, raw, *, field: str) -> Path:
    if not isinstance(raw, str):
        raise ToolchainError(f"{field} is not a path")
    path = Path(raw)
    return path.resolve() if path.is_absolute() else (project_root / path).resolve()


def _require_within(path: Path, root: Path, *, field: str) -> None:
    try:
        path.relative_to(root.resolve())
    except ValueError as error:
        raise ToolchainError(f"{field} is outside {root}") from error


def load_armips_lock(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_version") != 1:
        raise ToolchainError("unsupported armips lock schema")
    if document.get("tool") != "armips":
        raise ToolchainError("tool lock is not for armips")
    if document.get("repository") != OFFICIAL_ARMIPS_REPOSITORY:
        raise ToolchainError("armips repository is not the official source")
    license_lock = document.get("license", {})
    if license_lock.get("spdx") != "MIT":
        raise ToolchainError("armips license lock is not MIT")
    _require_sha256(
        license_lock.get("sha256"),
        field="license.sha256",
    )
    versions = document.get("versions")
    if not isinstance(versions, list) or {
        version.get("id") for version in versions
    } != {"reference_2023", "selected"}:
        raise ToolchainError(
            "armips lock must contain reference_2023 and selected"
        )
    for version in versions:
        label = f"versions.{version['id']}"
        _require_git_object(version.get("commit"), field=f"{label}.commit")
        _require_git_object(version.get("tree"), field=f"{label}.tree")
        _require_sha256(
            version.get("expected_binary_sha256"),
            field=f"{label}.expected_binary_sha256",
        )
        if not isinstance(version.get("source_date_epoch"), int):
            raise ToolchainError(f"{label}.source_date_epoch is invalid")
        for path_field in ("source_path", "bootstrap_path"):
            if not isinstance(version.get(path_field), str):
                raise ToolchainError(f"{label}.{path_field} is invalid")
    return document


def validate_platform(lock: Mapping) -> dict:
    expected = lock.get("platform_lock", {})
    actual = {
        "system": platform.system(),
        "machine": platform.machine(),
        "cmake": _version_line("cmake").removeprefix("cmake version "),
        "ninja": _version_line("ninja"),
    }
    for field in ("system", "machine", "cmake", "ninja"):
        if actual[field] != expected.get(field):
            raise ToolchainError(
                f"platform {field} mismatch: "
                f"expected {expected.get(field)!r}, got {actual[field]!r}"
            )
    return actual


def _bootstrap_source(
    destination: Path,
    *,
    repository: str,
    commit: str,
    work_root: Path,
) -> None:
    _require_within(
        destination,
        work_root,
        field="bootstrap destination",
    )
    if destination.exists():
        raise ToolchainError(
            f"bootstrap destination already exists: {destination}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    _checked_command(
        (
            "git",
            "clone",
            "--no-checkout",
            repository,
            str(destination),
        )
    )
    _git(destination, "checkout", "--detach", commit)


def resolve_and_validate_source(
    project_root: Path,
    work_root: Path,
    lock: Mapping,
    version: Mapping,
    *,
    bootstrap_missing: bool,
) -> tuple[Path, str]:
    configured = (
        ("source_path", version["source_path"]),
        ("bootstrap_path", version["bootstrap_path"]),
    )
    selected = next(
        (
            (field, _repo_path(project_root, raw, field=field))
            for field, raw in configured
            if _repo_path(project_root, raw, field=field).exists()
        ),
        None,
    )
    if selected is None:
        if not bootstrap_missing:
            raise ToolchainError(
                f"armips source missing for {version['id']}; "
                "use --bootstrap-missing to clone official source"
            )
        field = "bootstrap_path"
        source = _repo_path(
            project_root,
            version[field],
            field=field,
        )
        _bootstrap_source(
            source,
            repository=lock["repository"],
            commit=version["commit"],
            work_root=work_root,
        )
        selected = (field, source)

    source_field, source = selected
    if _git(source, "remote", "get-url", "origin") != lock["repository"]:
        raise ToolchainError(
            f"{version['id']} source remote is not pinned official armips"
        )
    if _git(source, "rev-parse", "HEAD") != version["commit"]:
        raise ToolchainError(f"{version['id']} source commit mismatch")
    if _git(source, "rev-parse", "HEAD^{tree}") != version["tree"]:
        raise ToolchainError(f"{version['id']} source tree mismatch")
    commit_timestamp = int(
        _git(source, "show", "-s", "--format=%ct", "HEAD")
    )
    if commit_timestamp != version["source_date_epoch"]:
        raise ToolchainError(
            f"{version['id']} SOURCE_DATE_EPOCH is not the "
            "pinned commit timestamp"
        )
    if _git(source, "status", "--porcelain=v1"):
        raise ToolchainError(f"{version['id']} source checkout is dirty")

    license_path = (source / lock["license"]["path"]).resolve()
    _require_within(
        license_path,
        source,
        field=f"{version['id']} license path",
    )
    if sha256_path(license_path) != lock["license"]["sha256"]:
        raise ToolchainError(f"{version['id']} license hash mismatch")
    return source, source_field


def _compiler_fingerprint(build_dir: Path) -> str:
    candidates = sorted(
        (build_dir / "CMakeFiles").glob(
            "*/CMakeCXXCompiler.cmake"
        )
    )
    if len(candidates) != 1:
        raise ToolchainError("cannot locate CMake C++ compiler metadata")
    text = candidates[0].read_text(encoding="utf-8")
    compiler_id = re.search(
        r'set\(CMAKE_CXX_COMPILER_ID "([^"]+)"\)',
        text,
    )
    version = re.search(
        r'set\(CMAKE_CXX_COMPILER_VERSION "([^"]+)"\)',
        text,
    )
    if compiler_id is None or version is None:
        raise ToolchainError("CMake compiler metadata is incomplete")
    return f"{compiler_id.group(1)} {version.group(1)}"


def build_armips_twice(
    source: Path,
    version: Mapping,
    lock: Mapping,
    destination: Path,
) -> tuple[dict, tuple[Path, Path]]:
    options = lock.get("build", {}).get("cmake_options", {})
    if not isinstance(options, dict):
        raise ToolchainError("armips cmake_options is invalid")
    generator = lock["build"].get("generator")
    build_type = lock["build"].get("type")
    hashes = []
    binaries = []
    compiler = None
    for ordinal, label in enumerate(("clean_a", "clean_b")):
        build_dir = destination / label
        environment = dict(os.environ)
        environment.update(
            {
                "LC_ALL": "C",
                "SOURCE_DATE_EPOCH": str(
                    version["source_date_epoch"]
                ),
                "TZ": "UTC",
            }
        )
        configure = [
            "cmake",
            "-S",
            str(source),
            "-B",
            str(build_dir),
            "-G",
            generator,
            f"-DCMAKE_BUILD_TYPE={build_type}",
        ]
        configure.extend(
            f"-D{name}={value}" for name, value in sorted(options.items())
        )
        _checked_command(configure, env=environment, capture=True)
        current_compiler = _compiler_fingerprint(build_dir)
        if current_compiler != lock["platform_lock"].get("compiler"):
            raise ToolchainError(
                "compiler mismatch: "
                f"expected {lock['platform_lock'].get('compiler')!r}, "
                f"got {current_compiler!r}"
            )
        if compiler is not None and current_compiler != compiler:
            raise ToolchainError("clean builds used different compilers")
        compiler = current_compiler
        _checked_command(
            ("cmake", "--build", str(build_dir), "--parallel"),
            env=environment,
            capture=True,
        )
        _checked_command(
            (
                "ctest",
                "--test-dir",
                str(build_dir),
                "--output-on-failure",
            ),
            env=environment,
            capture=True,
        )
        binary = build_dir / "armips"
        if not binary.is_file():
            raise ToolchainError("armips build did not create armips")
        digest = sha256_path(binary)
        expected = version["expected_binary_sha256"]
        if digest != expected:
            raise ToolchainError(
                f"{version['id']} {label} binary hash mismatch: "
                f"expected {expected}, got {digest}"
            )
        hashes.append(digest)
        binaries.append(binary)
        print(
            f"{version['id']} {label}: "
            f"sha256={digest} ctest=pass",
            flush=True,
        )
    if hashes[0] != hashes[1]:
        raise ToolchainError(
            f"{version['id']} clean builds are not reproducible"
        )
    return (
        {
            "source_commit": version["commit"],
            "source_tree": version["tree"],
            "source_date_epoch": version["source_date_epoch"],
            "compiler": compiler,
            "clean_build_sha256": hashes,
            "clean_builds_identical": True,
            "ctest": "pass",
        },
        (binaries[0], binaries[1]),
    )


def _load_patch_contract(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_version") != 1:
        raise ToolchainError("unsupported patch-audit contract schema")
    targets = document.get("targets")
    if not isinstance(targets, list) or not targets:
        raise ToolchainError("patch-audit contract has no targets")
    return document


def _validate_file(path: Path, expected: Mapping, *, context: str) -> None:
    size = expected.get("size")
    if not isinstance(size, int) or path.stat().st_size != size:
        raise ToolchainError(f"{context} size mismatch")
    if sha256_path(path) != expected.get("sha256"):
        raise ToolchainError(f"{context} SHA-256 mismatch")


def _assemble_copy(
    binary: Path,
    *,
    asm_root: Path,
    script: str,
    input_path: Path,
    output_path: Path,
    target_id: str,
    font_properties: Path,
) -> bytes:
    if binary.suffix.lower() == ".exe":
        raise ToolchainError("refusing to execute a Windows armips binary")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(input_path, output_path)
    if target_id == "slps":
        arguments = (
            str(binary),
            script,
            "-strequ",
            "__SLPS_PATH__",
            str(output_path),
            "-strequ",
            "__PROP_PATH__",
            str(font_properties),
        )
    elif target_id == "kuro_stage":
        arguments = (
            str(binary),
            script,
            "-strequ",
            "__KURO_PATH__",
            str(output_path),
        )
    else:
        raise ToolchainError(f"unsupported project ASM target: {target_id}")
    _checked_command(arguments, cwd=asm_root)
    return output_path.read_bytes()


def verify_project_asm(
    project_root: Path,
    lock: Mapping,
    binaries: Mapping[str, Path],
    destination: Path,
) -> dict:
    project = lock.get("project_asm_check", {})
    asm_root = _repo_path(
        project_root,
        project.get("asm_root"),
        field="project_asm_check.asm_root",
    )
    upstream_root = Path(
        _git(asm_root, "rev-parse", "--show-toplevel")
    ).resolve()
    if upstream_root != project_root.parent.resolve():
        raise ToolchainError("ASM root is not in the adjacent upstream repo")
    if _git(upstream_root, "rev-parse", "HEAD") != project.get(
        "reference_commit"
    ):
        raise ToolchainError("adjacent upstream commit mismatch")
    if _git(upstream_root, "status", "--porcelain=v1"):
        raise ToolchainError("adjacent upstream repository is dirty")

    font_lock = project.get("font_properties", {})
    font_properties = _repo_path(
        project_root,
        font_lock.get("path"),
        field="project_asm_check.font_properties.path",
    )
    _validate_file(
        font_properties,
        font_lock,
        context="font_properties",
    )

    contract_path = (
        project_root
        / "config"
        / "patches"
        / "upstream-asm-audit.json"
    )
    contract = _load_patch_contract(contract_path)
    contract_targets = {
        target["id"]: target for target in contract["targets"]
    }
    locked_targets = project.get("targets")
    if not isinstance(locked_targets, list):
        raise ToolchainError("project ASM targets are invalid")
    if {target["id"] for target in locked_targets} != set(
        contract_targets
    ):
        raise ToolchainError(
            "armips lock and patch-audit target sets differ"
        )

    source_data = {}
    output_data = {}
    target_reports = []
    for target_lock in locked_targets:
        target_id = target_lock["id"]
        contract_target = contract_targets[target_id]
        if contract_target["script"] != target_lock["script"]:
            raise ToolchainError(f"{target_id} script lock mismatch")
        if contract_target["input"]["size"] != target_lock["input_size"]:
            raise ToolchainError(f"{target_id} input size locks differ")
        if (
            contract_target["input"]["sha256"]
            != target_lock["input_sha256"]
        ):
            raise ToolchainError(f"{target_id} input hash locks differ")
        if (
            contract_target["output"]["sha256"]
            != target_lock["output_sha256"]
        ):
            raise ToolchainError(f"{target_id} output hash locks differ")

        input_path = _repo_path(
            project_root,
            target_lock["input"],
            field=f"{target_id}.input",
        )
        _validate_file(
            input_path,
            {
                "size": target_lock["input_size"],
                "sha256": target_lock["input_sha256"],
            },
            context=f"{target_id} input",
        )
        source_data[target_id] = input_path.read_bytes()
        version_hashes = {}
        for version_id, binary in binaries.items():
            output = _assemble_copy(
                binary,
                asm_root=asm_root,
                script=target_lock["script"],
                input_path=input_path,
                output_path=(
                    destination / version_id / f"{target_id}.bin"
                ),
                target_id=target_id,
                font_properties=font_properties,
            )
            digest = hashlib.sha256(output).hexdigest()
            if len(output) != target_lock["input_size"]:
                raise ToolchainError(
                    f"{target_id} changed file size under {version_id}"
                )
            if digest != target_lock["output_sha256"]:
                raise ToolchainError(
                    f"{target_id} output hash mismatch under {version_id}"
                )
            version_hashes[version_id] = digest
            output_data[(version_id, target_id)] = output
        if len(set(version_hashes.values())) != 1:
            raise ToolchainError(
                f"{target_id} differs between pinned armips versions"
            )
        target_reports.append(
            {
                "id": target_id,
                "script": target_lock["script"],
                "input_size": target_lock["input_size"],
                "input_sha256": target_lock["input_sha256"],
                "output_sha256_by_version": version_hashes,
                "versions_identical": True,
            }
        )

    selected_binary = binaries["selected"]
    audit_reports = []
    for target_lock in locked_targets:
        target_id = target_lock["id"]
        target = contract_targets[target_id]
        input_path = _repo_path(
            project_root,
            target_lock["input"],
            field=f"{target_id}.input",
        )
        owner_outputs = {}
        for owner, owner_lock in sorted(target["owners"].items()):
            script = owner_lock.get("script")
            if not isinstance(script, str):
                raise ToolchainError(f"{target_id}.{owner} script missing")
            if not (asm_root / script).is_file():
                raise ToolchainError(
                    f"{target_id}.{owner} script does not exist"
                )
            owner_outputs[owner] = _assemble_copy(
                selected_binary,
                asm_root=asm_root,
                script=script,
                input_path=input_path,
                output_path=(
                    destination
                    / "owners"
                    / target_id
                    / f"{owner}.bin"
                ),
                target_id=target_id,
                font_properties=font_properties,
            )
        try:
            audit = audit_binary_patch(
                source_data[target_id],
                output_data[("selected", target_id)],
                target,
                owner_outputs=owner_outputs,
            )
        except PatchAuditError as error:
            raise ToolchainError(
                f"{target_id} patch audit failed: {error}"
            ) from error
        audit_reports.append(
            {
                "id": target_id,
                "status": "pass",
                **audit,
            }
        )

    return {
        "upstream_commit": project["reference_commit"],
        "upstream_clean": True,
        "font_properties": {
            "size": font_lock["size"],
            "sha256": font_lock["sha256"],
        },
        "targets": target_reports,
        "versions_identical_for_all_targets": True,
        "patch_audits": audit_reports,
    }


def validate_armips_toolchain(
    project_root: Path,
    lock_path: Path,
    *,
    bootstrap_missing: bool = False,
) -> dict:
    project_root = project_root.resolve()
    work_root = (project_root / "work").resolve()
    work_root.mkdir(parents=True, exist_ok=True)
    lock = load_armips_lock(lock_path)
    platform_report = validate_platform(lock)

    sources = {}
    source_reports = {}
    for version in lock["versions"]:
        source, selected_field = resolve_and_validate_source(
            project_root,
            work_root,
            lock,
            version,
            bootstrap_missing=bootstrap_missing,
        )
        sources[version["id"]] = source
        source_reports[version["id"]] = {
            "repository": lock["repository"],
            "source_location": selected_field,
            "commit": version["commit"],
            "tree": version["tree"],
            "license": {
                "spdx": lock["license"]["spdx"],
                "sha256": lock["license"]["sha256"],
            },
            "clean": True,
        }

    temporary_parent = work_root / "toolchain" / "tmp"
    temporary_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="armips-validation-",
        dir=temporary_parent,
    ) as raw_temporary:
        temporary = Path(raw_temporary)
        build_reports = {}
        first_binaries = {}
        for version in lock["versions"]:
            report, binaries = build_armips_twice(
                sources[version["id"]],
                version,
                lock,
                temporary / "build" / version["id"],
            )
            build_reports[version["id"]] = report
            first_binaries[version["id"]] = binaries[0]
        project_report = verify_project_asm(
            project_root,
            lock,
            first_binaries,
            temporary / "asm",
        )

    platform_report["compiler"] = lock["platform_lock"]["compiler"]
    return {
        "schema_version": 1,
        "content_policy": (
            "Source provenance, tool hashes, counts and binary-diff "
            "digests only; no game or patched bytes are embedded."
        ),
        "status": "pass",
        "tool": "armips",
        "repository": lock["repository"],
        "platform": platform_report,
        "sources": source_reports,
        "builds": build_reports,
        "project_asm": project_report,
        "completion_gates": {
            "two_clean_builds_identical": True,
            "pinned_versions_project_outputs_identical": True,
            "input_size_original_bytes_allowed_ranges_final_diff_output_hash": True,
            "unknown_input_rejected": True,
            "out_of_range_write_rejected": True,
            "implicit_overlap_rejected": True,
            "file_expansion_rejected": True
        },
    }


__all__ = [
    "OFFICIAL_ARMIPS_REPOSITORY",
    "ToolchainError",
    "build_armips_twice",
    "load_armips_lock",
    "resolve_and_validate_source",
    "sha256_path",
    "validate_armips_toolchain",
    "validate_platform",
    "verify_project_asm",
]
