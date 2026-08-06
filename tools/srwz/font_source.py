"""Fetch and verify the project's explicitly allowed font sources."""

from __future__ import annotations

import hashlib
import io
import json
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Mapping

from .diagnostics import require_work_output


ALLOWED_SOURCES = {
    "https://github.com/notofonts/noto-cjk.git": {
        "license": "OFL-1.1",
        "font_prefix": (
            "https://raw.githubusercontent.com/notofonts/noto-cjk/"
        ),
        "license_prefix": (
            "https://raw.githubusercontent.com/notofonts/noto-cjk/"
        ),
    },
    "https://github.com/lxgw/LxgwNeoXiZhi-Screen.git": {
        "license": "IPA",
        "font_prefix": (
            "https://github.com/lxgw/LxgwNeoXiZhi-Screen/"
            "releases/download/"
        ),
        "license_prefix": (
            "https://raw.githubusercontent.com/lxgw/"
            "LxgwNeoXiZhi-Screen/"
        ),
    },
}

LOCAL_NONCOMMERCIAL_SOURCE_KIND = "local-noncommercial-test"
LOCAL_NONCOMMERCIAL_DISTRIBUTION = "local_noncommercial_test_only"
LOCAL_NONCOMMERCIAL_LICENSE = "LicenseRef-Noncommercial-Unverified"
PINNED_OFFICIAL_ARCHIVE_SOURCE_KIND = "pinned-official-archive"
HARMONYOS_SOURCE_ID = "huawei-harmonyos-sans"
HARMONYOS_ARCHIVE_URL_PREFIX = (
    "https://communityfile-drcn.op.dbankcloud.cn/FileServer/getFile/"
)
HARMONYOS_LICENSE = "LicenseRef-HarmonyOS-Sans-Fonts-License"
HARMONYOS_DISTRIBUTION = "commercial_use_with_notice"


class FontSourceError(ValueError):
    """A pinned font source is invalid or cannot be reproduced."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_font_lock(path: Path) -> dict:
    try:
        lock = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FontSourceError(f"cannot read font lock: {path}") from error
    validate_font_lock(lock)
    return lock


def _validate_file_record(item: object, label: str) -> None:
    if not isinstance(item, Mapping):
        raise FontSourceError(f"font lock has no {label} object")
    if (
        not isinstance(item.get("path"), str)
        or not item["path"].startswith("work/font-source/")
    ):
        raise FontSourceError(f"{label} output is outside font-source")
    if not isinstance(item.get("size"), int) or item["size"] <= 0:
        raise FontSourceError(f"{label} size is invalid")
    digest = item.get("sha256")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise FontSourceError(f"{label} SHA-256 is invalid")


def validate_font_lock(lock: Mapping) -> None:
    if lock.get("schema_version") != 1:
        raise FontSourceError("unsupported font lock schema")
    if lock.get("source_kind") == LOCAL_NONCOMMERCIAL_SOURCE_KIND:
        if lock.get("distribution") != LOCAL_NONCOMMERCIAL_DISTRIBUTION:
            raise FontSourceError(
                "local noncommercial font distribution policy is invalid"
            )
        if lock.get("license", {}).get("spdx") != (
            LOCAL_NONCOMMERCIAL_LICENSE
        ):
            raise FontSourceError(
                "local noncommercial font license marker is invalid"
            )
        for label in ("font", "license"):
            _validate_file_record(lock.get(label), label)
        if lock["license"].get("status") != "provenance_only_not_a_license":
            raise FontSourceError(
                "local noncommercial provenance status is invalid"
            )
        return
    if lock.get("source_kind") == PINNED_OFFICIAL_ARCHIVE_SOURCE_KIND:
        if lock.get("source_id") != HARMONYOS_SOURCE_ID:
            raise FontSourceError("official archive source is not allowed")
        if lock.get("distribution") != HARMONYOS_DISTRIBUTION:
            raise FontSourceError("HarmonyOS font distribution policy is invalid")
        if lock.get("license", {}).get("spdx") != HARMONYOS_LICENSE:
            raise FontSourceError("HarmonyOS font license marker is invalid")
        archive = lock.get("archive")
        if not isinstance(archive, Mapping):
            raise FontSourceError("font lock has no archive object")
        url = archive.get("url")
        if not isinstance(url, str) or not url.startswith(
            HARMONYOS_ARCHIVE_URL_PREFIX
        ):
            raise FontSourceError("archive URL is not an allowed source")
        if not isinstance(archive.get("size"), int) or archive["size"] <= 0:
            raise FontSourceError("archive size is invalid")
        archive_digest = archive.get("sha256")
        if (
            not isinstance(archive_digest, str)
            or len(archive_digest) != 64
            or any(
                character not in "0123456789abcdef"
                for character in archive_digest
            )
        ):
            raise FontSourceError("archive SHA-256 is invalid")
        members = set()
        for label in ("font", "license"):
            item = lock.get(label)
            _validate_file_record(item, label)
            member = item.get("archive_member")
            if (
                not isinstance(member, str)
                or not member
                or member.startswith("/")
                or ".." in Path(member).parts
                or member in members
            ):
                raise FontSourceError(f"{label} archive member is invalid")
            members.add(member)
        if lock["license"].get("notice_required") is not True:
            raise FontSourceError("HarmonyOS font notice requirement is missing")
        return
    repository = lock.get("repository")
    policy = ALLOWED_SOURCES.get(repository)
    if policy is None:
        raise FontSourceError(f"font repository is not allowed: {repository}")
    if lock.get("license", {}).get("spdx") != policy["license"]:
        raise FontSourceError("font license does not match source policy")

    commit = lock.get("commit")
    if (
        not isinstance(commit, str)
        or len(commit) != 40
        or any(character not in "0123456789abcdef" for character in commit)
    ):
        raise FontSourceError("font lock commit is not a full SHA-1")

    for label in ("font", "license"):
        item = lock.get(label)
        if not isinstance(item, Mapping):
            raise FontSourceError(f"font lock has no {label} object")
        url = item.get("url")
        if (
            not isinstance(url, str)
            or not url.startswith(policy[f"{label}_prefix"])
        ):
            raise FontSourceError(f"{label} URL is not an allowed source")
        _validate_file_record(item, label)

    if repository.endswith("/noto-cjk.git"):
        pinned_prefix = policy["font_prefix"] + commit + "/"
        if not lock["font"]["url"].startswith(pinned_prefix):
            raise FontSourceError("Noto font URL is not commit pinned")
        if not lock["license"]["url"].startswith(pinned_prefix):
            raise FontSourceError("Noto license URL is not commit pinned")
    else:
        tag = lock.get("tag")
        if not isinstance(tag, str) or not tag:
            raise FontSourceError("release font lock has no tag")
        expected_font_prefix = policy["font_prefix"] + tag + "/"
        expected_license_prefix = policy["license_prefix"] + commit + "/"
        if not lock["font"]["url"].startswith(expected_font_prefix):
            raise FontSourceError("font URL is not release-tag pinned")
        if not lock["license"]["url"].startswith(expected_license_prefix):
            raise FontSourceError("license URL is not commit pinned")


def _download(url: str, expected: Mapping) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "srwz-zh-clean-room-font-fetch/2"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read(expected["size"] + 1)
    except (OSError, urllib.error.URLError) as error:
        raise FontSourceError(f"font download failed: {url}") from error
    if len(data) != expected["size"]:
        raise FontSourceError(
            f"download size mismatch: expected {expected['size']}, "
            f"got {len(data)}"
        )
    digest = sha256_bytes(data)
    if digest != expected["sha256"]:
        raise FontSourceError(
            "download SHA-256 mismatch: "
            f"expected {expected['sha256']}, got {digest}"
        )
    return data


def fetch_font_lock(
    project_root: Path,
    work_root: Path,
    lock_path: Path,
    *,
    force: bool = False,
) -> tuple[Path, ...]:
    lock = load_font_lock(lock_path)
    if lock.get("source_kind") == LOCAL_NONCOMMERCIAL_SOURCE_KIND:
        raise FontSourceError(
            "local noncommercial font locks are verification-only and "
            "cannot be downloaded"
        )
    if lock.get("source_kind") == PINNED_OFFICIAL_ARCHIVE_SOURCE_KIND:
        existing_outputs = tuple(
            require_work_output(
                project_root / lock[label]["path"],
                work_root,
            )
            for label in ("font", "license")
        )
        if not force:
            existing_matches = []
            for label, output in zip(("font", "license"), existing_outputs):
                if not output.exists():
                    existing_matches.append(False)
                    continue
                data = output.read_bytes()
                if (
                    len(data) != lock[label]["size"]
                    or sha256_bytes(data) != lock[label]["sha256"]
                ):
                    raise FontSourceError(
                        f"existing {label} does not match lock; use --force"
                    )
                existing_matches.append(True)
            if all(existing_matches):
                return existing_outputs
        archive_data = _download(lock["archive"]["url"], lock["archive"])
        try:
            archive = zipfile.ZipFile(io.BytesIO(archive_data))
            member_data = {
                label: archive.read(lock[label]["archive_member"])
                for label in ("font", "license")
            }
        except (KeyError, OSError, zipfile.BadZipFile) as error:
            raise FontSourceError("font archive cannot be read") from error
        outputs = []
        for label in ("font", "license"):
            expected = lock[label]
            data = member_data[label]
            if (
                len(data) != expected["size"]
                or sha256_bytes(data) != expected["sha256"]
            ):
                raise FontSourceError(
                    f"archive {label} does not match its lock"
                )
            output = require_work_output(
                project_root / expected["path"],
                work_root,
            )
            if output.exists() and not force:
                existing = output.read_bytes()
                if existing != data:
                    raise FontSourceError(
                        f"existing {label} does not match lock; use --force"
                    )
            else:
                output.parent.mkdir(parents=True, exist_ok=True)
                temporary = output.with_suffix(output.suffix + ".tmp")
                temporary.write_bytes(data)
                temporary.replace(output)
            outputs.append(output)
        return tuple(outputs)

    outputs = []
    for label in ("font", "license"):
        expected = lock[label]
        output = require_work_output(
            project_root / expected["path"],
            work_root,
        )
        if output.exists() and not force:
            data = output.read_bytes()
            if (
                len(data) != expected["size"]
                or sha256_bytes(data) != expected["sha256"]
            ):
                raise FontSourceError(
                    f"existing {label} does not match lock; use --force"
                )
        else:
            data = _download(expected["url"], expected)
            output.parent.mkdir(parents=True, exist_ok=True)
            temporary = output.with_suffix(output.suffix + ".tmp")
            temporary.write_bytes(data)
            temporary.replace(output)
        outputs.append(output)
    return tuple(outputs)


def verify_font_lock_files(
    project_root: Path,
    work_root: Path,
    lock: Mapping,
) -> dict[str, Path]:
    validate_font_lock(lock)
    outputs = {}
    for label in ("font", "license"):
        expected = lock[label]
        path = require_work_output(
            project_root / expected["path"],
            work_root,
        )
        if not path.is_file():
            raise FontSourceError(
                f"locked {label} is missing; run the matching fetch tool"
            )
        data = path.read_bytes()
        if (
            len(data) != expected["size"]
            or sha256_bytes(data) != expected["sha256"]
        ):
            raise FontSourceError(f"locked {label} does not match its lock")
        outputs[label] = path
    return outputs


def font_source_metadata(lock: Mapping) -> dict:
    """Return the stable proposal/build identity for one validated lock."""

    validate_font_lock(lock)
    metadata = {
        "family": lock["family"],
        "version": lock["version"],
        "font_sha256": lock["font"]["sha256"],
        "license_spdx": lock["license"]["spdx"],
        "license_sha256": lock["license"]["sha256"],
    }
    for key in ("source_kind", "source_id", "distribution", "commit"):
        value = lock.get(key)
        if value is not None:
            metadata[key] = value
    return metadata


def verify_font_fallbacks(
    project_root: Path,
    work_root: Path,
    references: object,
) -> tuple[dict[str, Path], tuple[dict, ...]]:
    """Verify explicit missing-glyph fallbacks using the primary geometry."""

    if references is None:
        return {}, ()
    if not isinstance(references, list):
        raise FontSourceError("font fallbacks must be a list")
    paths: dict[str, Path] = {}
    reports = []
    for reference in references:
        if not isinstance(reference, Mapping):
            raise FontSourceError("font fallback is malformed")
        lock_reference = reference.get("font_lock")
        characters = reference.get("characters")
        reason = reference.get("reason")
        if (
            not isinstance(lock_reference, str)
            or not lock_reference
            or not isinstance(characters, str)
            or not characters
            or len(set(characters)) != len(characters)
            or not isinstance(reason, str)
            or not reason
        ):
            raise FontSourceError("font fallback selection is invalid")
        lock_path = (project_root / lock_reference).resolve()
        try:
            lock_path.relative_to(project_root.resolve())
        except ValueError as error:
            raise FontSourceError("font fallback lock escapes project") from error
        lock = load_font_lock(lock_path)
        verified = verify_font_lock_files(project_root, work_root, lock)
        for character in characters:
            if character in paths:
                raise FontSourceError(
                    f"font fallback character is repeated: {character!r}"
                )
            paths[character] = verified["font"]
        reports.append(
            {
                "font_lock": lock_reference,
                "characters": characters,
                "character_count": len(characters),
                "reason": reason,
                "font_source": font_source_metadata(lock),
                "uses_primary_rasterizer_geometry": True,
            }
        )
    return paths, tuple(reports)


__all__ = [
    "ALLOWED_SOURCES",
    "FontSourceError",
    "font_source_metadata",
    "fetch_font_lock",
    "load_font_lock",
    "sha256_bytes",
    "validate_font_lock",
    "verify_font_lock_files",
    "verify_font_fallbacks",
]
