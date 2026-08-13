"""Source-driven outer punctuation rules for SRWZ STAGE dialogue."""

from __future__ import annotations

import re
from dataclasses import dataclass


SPOKEN_QUOTE = "spoken_quote"
PARENTHETICAL = "parenthetical"
UNQUOTED = "unquoted"
KEYWORD_EXEMPT = "keyword_exempt"
UNKNOWN = "unknown"

_CONTINUATION = re.compile(r"\n[　 ]*")


@dataclass(frozen=True)
class StoryQuoteVerdict:
    """Expected and observed outer-punctuation styles for one STAGE record."""

    expected: str
    actual: str
    exact: bool


def logical_outer_text(text: str) -> str:
    """Collapse authoring wraps while preserving the visible text itself."""

    return _CONTINUATION.sub("", text).strip(" 　")


def source_quote_style(
    source_text: str,
    speaker_text: str,
    *,
    has_keyword_links: bool,
) -> str:
    """Derive the Chinese outer-punctuation rule from native STAGE structure.

    Runtime keyword records are deliberately exempt: their invisible link
    controls and visible outer punctuation are validated by the dedicated
    keyword pipeline.  A blank/whitespace speaker is a location or system
    card, not spoken dialogue.  Two native tutorial records are missing their
    closing corner quote, so a leading or trailing native quote is sufficient
    evidence that the record is spoken dialogue.
    """

    if has_keyword_links:
        return KEYWORD_EXEMPT
    visible = logical_outer_text(source_text)
    if not speaker_text.strip(" 　"):
        return UNQUOTED
    if visible.startswith("（") and visible.endswith("）"):
        return PARENTHETICAL
    if visible.startswith(("「", "『")) or visible.endswith(("」", "』")):
        return SPOKEN_QUOTE
    return UNKNOWN


def translated_quote_style(translated_text: str) -> str:
    """Classify the visible outer punctuation of one Chinese translation."""

    visible = logical_outer_text(translated_text)
    if visible.startswith("“") and visible.endswith("”"):
        return SPOKEN_QUOTE
    if visible.startswith("（") and visible.endswith("）"):
        return PARENTHETICAL
    if visible.startswith(("「", "『")) and visible.endswith(("」", "』")):
        return "native_quote"
    if visible.startswith(("“", "”", "「", "」", "『", "』", "（", "）")):
        return "malformed_outer_punctuation"
    if visible.endswith(("“", "”", "「", "」", "『", "』", "（", "）")):
        return "malformed_outer_punctuation"
    return UNQUOTED


def evaluate_story_quote(
    source_text: str,
    translated_text: str,
    speaker_text: str,
    *,
    has_keyword_links: bool,
) -> StoryQuoteVerdict:
    """Evaluate one translated record without modifying its text."""

    expected = source_quote_style(
        source_text,
        speaker_text,
        has_keyword_links=has_keyword_links,
    )
    actual = translated_quote_style(translated_text)
    return StoryQuoteVerdict(
        expected=expected,
        actual=actual,
        exact=(expected == KEYWORD_EXEMPT or expected == actual),
    )


__all__ = [
    "KEYWORD_EXEMPT",
    "PARENTHETICAL",
    "SPOKEN_QUOTE",
    "StoryQuoteVerdict",
    "UNKNOWN",
    "UNQUOTED",
    "evaluate_story_quote",
    "logical_outer_text",
    "source_quote_style",
    "translated_quote_style",
]
