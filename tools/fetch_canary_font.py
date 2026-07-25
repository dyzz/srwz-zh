#!/usr/bin/env python3
"""Fetch and verify the pinned official OFL Noto CJK canary font."""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path

from srwz.diagnostics import require_work_output


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_LOCK = (
    PROJECT_ROOT / "config" / "fonts" / "noto-sans-cjk-sc.lock.json"
)
OFFICIAL_RAW_PREFIX = (
    "https://raw.githubusercontent.com/notofonts/noto-cjk/"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download only the pinned official Noto Sans CJK SC font and "
            "its OFL-1.1 license into ignored work/."
        )
    )
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _download(url: str, expected: dict) -> bytes:
    if not url.startswith(OFFICIAL_RAW_PREFIX):
        raise SystemExit(f"refusing non-official font URL: {url}")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "srwz-zh-clean-room-font-fetch/1"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read(expected["size"] + 1)
    if len(data) != expected["size"]:
        raise SystemExit(
            f"download size mismatch: expected {expected['size']}, "
            f"got {len(data)}"
        )
    digest = _sha256(data)
    if digest != expected["sha256"]:
        raise SystemExit(
            f"download SHA-256 mismatch: "
            f"expected {expected['sha256']}, got {digest}"
        )
    return data


def main() -> int:
    args = parse_args()
    lock = json.loads(args.lock.read_text(encoding="utf-8"))
    if lock.get("schema_version") != 1:
        raise SystemExit("unsupported font lock schema")
    if lock.get("repository") != (
        "https://github.com/notofonts/noto-cjk.git"
    ):
        raise SystemExit("font lock is not the official Noto CJK source")
    if lock.get("license", {}).get("spdx") != "OFL-1.1":
        raise SystemExit("font lock is not OFL-1.1")

    for label in ("font", "license"):
        expected = lock[label]
        output = require_work_output(_resolve(expected["path"]), WORK_ROOT)
        if output.exists() and not args.force:
            data = output.read_bytes()
            if (
                len(data) != expected["size"]
                or _sha256(data) != expected["sha256"]
            ):
                raise SystemExit(
                    f"existing {label} does not match lock; use --force"
                )
            print(f"[OK] {output}")
            continue
        data = _download(expected["url"], expected)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(data)
        print(f"[OK] {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
