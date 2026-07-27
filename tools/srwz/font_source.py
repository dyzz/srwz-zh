"""Fetch and verify the project's explicitly allowed font sources."""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
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


def validate_font_lock(lock: Mapping) -> None:
    if lock.get("schema_version") != 1:
        raise FontSourceError("unsupported font lock schema")
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
            or any(
                character not in "0123456789abcdef"
                for character in digest
            )
        ):
            raise FontSourceError(f"{label} SHA-256 is invalid")

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


__all__ = [
    "ALLOWED_SOURCES",
    "FontSourceError",
    "fetch_font_lock",
    "load_font_lock",
    "sha256_bytes",
    "validate_font_lock",
    "verify_font_lock_files",
]
