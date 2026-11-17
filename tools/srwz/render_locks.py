"""Output locks of build-time renders, and the authoring mode that re-freezes them.

A renderer that draws text into pixels at build time compares what it produced with a hash its contract
recorded. Normally a mismatch fails the build. Inside ``relocking()`` (used only by authoring tools such as
tools/zh_hant/author_textures.py, never by builds) a mismatch instead writes the produced value into the
contract object in place and is listed in the returned record, so the caller can save the updated contract.
"""
from __future__ import annotations

from contextlib import contextmanager

_record: list | None = None


@contextmanager
def relocking():
    global _record
    previous, _record = _record, []
    try:
        yield _record
    finally:
        _record = previous


def output_lock(actual, owner, key) -> bool:
    """True when ``owner[key] == actual``; while relocking, store ``actual`` there and return True."""
    try:
        expected = owner[key]
    except (KeyError, IndexError, TypeError):
        expected = None
    if expected == actual:
        return True
    if _record is None:
        return False
    owner[key] = actual
    _record.append((key, expected, actual))
    return True
