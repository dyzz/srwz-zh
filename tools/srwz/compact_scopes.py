"""Author notation ``<z>RUN</z>`` for compact Latin/digit scopes in story text.

The corpus stores ``<z>…</z>``; layout tools and encoders see native controls.
Every scope sets width, advance and height explicitly and restores all three,
so no dimension depends on what an earlier string left in the explicit state.
The first control in a row leaves classification mode for the rest of that
row, which is why the restore must repeat the native body metrics.
"""
from __future__ import annotations

import re

# Native story message/narration body: 21/12/21/14 (Original 0x41E770,
# SP 0x479F60). Letters keep the 14x11 the untagged height state produced
# before; digits were 14x10 and sat high, so the 2026-10-24 LRPS2 review set
# them to 11 as well. Height 10, if ever used, is 0x8A: 33 0A is a line feed.
STORY = dict(width=0x0E, space=0x0C, letter=0x0B, digit=0x0B,
             restore_width=0x15, restore_space=0x15, restore_height=0x0C)
# SP library flow synopsis body: 16/16/10. Narrower 12/11 than the old 14/12;
# digits height 9 as the native auto rule drew them, letters height 10 (0x8A).
FLOW_SYNOPSIS = dict(width=0x0C, space=0x0B, letter=0x8A, digit=0x09,
                     restore_width=0x10, restore_space=0x10, restore_height=0x8A)

# ASCII ( ) encode as raw single bytes that desync the two-byte parser, and
# [n] is a native numeric parameter protocol: only fullwidth （） are allowed.
VISIBLE = r"A-Za-z0-9Ａ-Ｚａ-ｚ０-９ .,:：．_'/／＋+％%~～〜×÷±＝=　－−·《》（）-"
SCOPE = re.compile(rf"<z>([{VISIBLE}]+)</z>")
TAG = re.compile(r"</?z>")
_EXPANDED = re.compile(
    r"<width:([0-9A-F]{2})><space:([0-9A-F]{2})><height:[0-9A-F]{2}>"
    rf"((?:[{VISIBLE}]|<height:[0-9A-F]{{2}}>)+?)"
    r"(?:<width:[0-9A-F]{2}><space:[0-9A-F]{2}>|<space:[0-9A-F]{2}><width:[0-9A-F]{2}>)"
    r"<height:[0-9A-F]{2}>"
)


def _kind(character: str) -> str | None:
    if character.isascii() and character.isdigit() or "０" <= character <= "９":
        return "digit"
    if character.isalpha():
        return "letter"
    return None


def expand_scope(run: str, metrics: dict = STORY) -> str:
    """Native controls for one run; punctuation keeps the preceding height.

    A STAGE keyword body 《…》 must stay byte-identical to its catalog entry,
    so it gets one height (that of its first letter or digit), no switches.
    """
    kinds = [_kind(c) for c in run]
    current = next((k for k in kinds if k), "letter")
    parts, active, keyword = [], None, False
    for character, kind in zip(run, kinds):
        keyword = character == "《" or keyword and character != "》"
        if not (keyword and active is not None):
            current = kind or current
        if metrics[current] != active:
            active = metrics[current]
            parts.append(f"<height:{active:02X}>")
        parts.append(character)
    opening = f"<width:{metrics['width']:02X}><space:{metrics['space']:02X}>"
    width = f"<width:{metrics['restore_width']:02X}>"
    space = f"<space:{metrics['restore_space']:02X}>"
    # A trailing percent sign is kept apart from a following width tag.
    restore = space + width if run.endswith(("%", "％")) else width + space
    return (opening + parts[0] + "".join(parts[1:]) + restore
            + f"<height:{metrics['restore_height']:02X}>")


def expand(text: str, metrics: dict = STORY) -> str:
    """Replace every ``<z>…</z>`` with native controls; reject stray tags."""
    expanded = SCOPE.sub(lambda m: expand_scope(m[1], metrics), text)
    stray = TAG.search(expanded)
    if stray:
        raise ValueError(f"malformed or nested <z> scope at character {stray.start()}: {text!r}")
    return expanded


def collapse(text: str, metrics: dict = STORY) -> str:
    """Inverse of :func:`expand` for scopes it generated; other controls stay."""
    def back(match):
        scoped = "<z>" + re.sub(r"<height:[0-9A-F]{2}>", "", match[3]) + "</z>"
        return scoped if expand(scoped, metrics) == match.group() else match.group()
    return _EXPANDED.sub(back, text)
