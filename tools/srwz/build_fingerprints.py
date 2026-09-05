"""Semantic identities shared by the font and text build consumers."""

from __future__ import annotations

import hashlib
import json
from typing import Mapping


def font_binary_signature(proposal: Mapping[str, object]) -> str:
    """Exclude only corpus-selection bookkeeping, retaining every font input."""

    return hashlib.sha256(
        json.dumps(
            {key: value for key, value in proposal.items() if key != "ui_selection"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
