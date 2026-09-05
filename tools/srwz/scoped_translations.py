"""Entry-specific corrections that must not affect shared source translations."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping


def load_scoped_translations(rows: object) -> dict[str, dict]:
    if not isinstance(rows, list):
        raise ValueError("scoped translations must be an array")
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("invalid scoped translation")
        entry_id = row.get("id")
        if not isinstance(entry_id, str) or not entry_id or entry_id in result:
            raise ValueError("missing or duplicate scoped translation ID")
        for key in ("source_text_sha256", "context_text_sha256"):
            if key == "context_text_sha256" and key not in row:
                continue
            if not isinstance(row.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", row[key]):
                raise ValueError(f"invalid {key}: {entry_id}")
        if not isinstance(row.get("translation"), str) or not row["translation"]:
            raise ValueError(f"empty scoped translation: {entry_id}")
        result[entry_id] = dict(row)
    return result


def resolve_scoped_translation(
    overrides: Mapping[str, dict], entry_id: str, source_text: str,
    default: str, *, context_text: str | None = None,
) -> str:
    row = overrides.get(entry_id)
    if row is None:
        return default
    for key, text in (("source_text_sha256", source_text), ("context_text_sha256", context_text)):
        if key not in row:
            continue
        if text is None or hashlib.sha256(text.encode("utf-8")).hexdigest() != row[key]:
            raise ValueError(f"scoped translation preimage drift ({key}): {entry_id}")
    return row["translation"]


def verify_scoped_translation_coverage(overrides: Mapping[str, dict], used: Iterable[str]) -> None:
    missing = set(overrides) - set(used)
    if missing:
        raise ValueError(f"unused scoped translations: {sorted(missing)}")
