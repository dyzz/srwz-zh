"""Deterministic Chinese dialogue reflow for the SRWZ message window."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, Sequence

from .text import RUNTIME_FORMAT_TOKEN


DEFAULT_LINE_WIDTH = 24
DEFAULT_MAX_LINES = 3
PLAYER_NAME_RENDER_WIDTH = 6
CONTINUATION_INDENT = "　"
COMMON_PROTECTED_WORDS = (
    "中距离",
    "兵器",
    "刚才",
    "开发",
    "战役",
    "本身",
    "不是",
    "那样",
    "我们",
    "项目",
)

_STRUCTURAL_TOKEN = re.compile(
    r"\$[A-Za-z]"
    rf"|{RUNTIME_FORMAT_TOKEN.pattern}"
    r"|\{[0-9A-Fa-f]{2}\}"
    r"|<[A-Za-z0-9_]+:[0-9A-Fa-f]{2}>"
)
_LATIN_TERM = re.compile(r"[A-Za-z0-9]+(?:[ .·_-][A-Za-z0-9]+)*")
_TITLE = re.compile(r"《[^》\n]{1,22}》|‘[^’\n]{1,22}’")
_SEPARATE_QUOTED_LINES = re.compile(r"”\n[　 ]*“")

_STRONG_BREAK_END = frozenset("。！？!?")
_CLAUSE_BREAK_END = frozenset("，、；：,;:")
_WEAK_BREAK_END = frozenset("…—")
_CLOSING_PUNCTUATION = frozenset("，。！？；：、,.!?;:％%”’）》】〕〉」』…—")
_OPENING_PUNCTUATION = frozenset("“‘（《【〔〈「『")
_MODAL_PARTICLES = frozenset("啊呀呢吗吧嘛么啦哟哦")
FORBIDDEN_LINE_START_CHARACTERS = _CLOSING_PUNCTUATION | _MODAL_PARTICLES
FORBIDDEN_LINE_END_CHARACTERS = _OPENING_PUNCTUATION


class ChineseLayoutError(ValueError):
    """A dialogue string cannot fit the configured Chinese layout."""


@dataclass(frozen=True)
class LayoutToken:
    text: str
    width: int


@dataclass(frozen=True)
class ReflowResult:
    original: str
    text: str
    preserved_reason: str
    line_widths: tuple[int, ...]

    @property
    def changed(self) -> bool:
        return self.original != self.text


def logical_dialogue_text(text: str) -> str:
    """Remove authoring newlines and their continuation indentation."""

    return re.sub(r"\n[　 ]*", "", text)


def _structural_width(token: str) -> int:
    if token.startswith(("{", "<")):
        return 0
    if token.startswith(("$", "%")):
        return PLAYER_NAME_RENDER_WIDTH
    raise AssertionError(f"not structural notation: {token!r}")


@lru_cache(maxsize=8)
def _normalize_protected_terms(
    protected_terms: tuple[str, ...],
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                term
                for term in protected_terms
                if isinstance(term, str) and len(term) > 1 and "\n" not in term
            },
            key=lambda term: (-len(term), term),
        )
    )


@lru_cache(maxsize=8)
def _protected_term_index(
    protected_terms: tuple[str, ...],
) -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = {}
    for term in protected_terms:
        grouped.setdefault(term[0], []).append(term)
    return {character: tuple(terms) for character, terms in grouped.items()}


def _protected_match(
    text: str,
    offset: int,
    protected_terms: dict[str, tuple[str, ...]],
) -> str:
    for term in protected_terms.get(text[offset], ()):
        if text.startswith(term, offset):
            return term
    return ""


def tokenize_dialogue(
    text: str,
    *,
    protected_terms: Iterable[str] = (),
) -> tuple[LayoutToken, ...]:
    """Split text into renderer-width units without splitting names/tokens."""

    terms = _normalize_protected_terms(
        (*tuple(protected_terms), *COMMON_PROTECTED_WORDS)
    )
    term_index = _protected_term_index(terms)
    tokens = []
    offset = 0
    while offset < len(text):
        structural = _STRUCTURAL_TOKEN.match(text, offset)
        if structural is not None:
            token = structural.group(0)
            tokens.append(LayoutToken(token, _structural_width(token)))
            offset = structural.end()
            continue

        candidates = []
        protected = _protected_match(text, offset, term_index)
        if protected:
            candidates.append(protected)
        for pattern in (_TITLE, _LATIN_TERM):
            match = pattern.match(text, offset)
            if match is not None:
                candidates.append(match.group(0))
        if text.startswith(("……", "——"), offset):
            candidates.append(text[offset : offset + 2])
        if candidates:
            token = max(candidates, key=lambda candidate: (len(candidate), candidate))
            tokens.append(LayoutToken(token, len(token)))
            offset += len(token)
            continue

        tokens.append(LayoutToken(text[offset], 1))
        offset += 1
    return tuple(tokens)


def rendered_line_width(
    text: str,
    *,
    protected_terms: Iterable[str] = (),
) -> int:
    """Return fixed-cell width, expanding runtime string placeholders."""

    content = text.lstrip("　 ")
    return sum(
        token.width
        for token in tokenize_dialogue(
            content,
            protected_terms=protected_terms,
        )
    )


def dialogue_line_widths(
    text: str,
    *,
    protected_terms: Iterable[str] = (),
) -> tuple[int, ...]:
    return tuple(
        rendered_line_width(line, protected_terms=protected_terms)
        for line in text.splitlines()
    )


def _valid_break(tokens: Sequence[LayoutToken], index: int) -> bool:
    previous = tokens[index - 1].text
    following = tokens[index].text
    if previous[-1] in _OPENING_PUNCTUATION:
        return False
    if following[0] in _CLOSING_PUNCTUATION:
        return False
    if following[0] in _MODAL_PARTICLES:
        return False
    return True


def _break_penalty(previous: str) -> int:
    last = previous[-1]
    if last in _STRONG_BREAK_END:
        return 0
    if last in _WEAK_BREAK_END:
        return 25
    if last in _CLAUSE_BREAK_END:
        return 40
    return 400


def _partition_tokens(
    tokens: Sequence[LayoutToken],
    *,
    line_width: int,
    max_lines: int,
    preferred_break_offsets: frozenset[int] = frozenset(),
) -> tuple[tuple[int, int], ...]:
    if not tokens:
        return ((0, 0),)
    if any(token.width > line_width for token in tokens):
        oversized = max(tokens, key=lambda token: token.width)
        raise ChineseLayoutError(
            f"indivisible term exceeds {line_width} cells: {oversized.text!r}"
        )

    prefix = [0]
    character_offsets = [0]
    for token in tokens:
        prefix.append(prefix[-1] + token.width)
        character_offsets.append(character_offsets[-1] + len(token.text))
    total_width = prefix[-1]
    minimum_lines = max(1, (total_width + line_width - 1) // line_width)

    def width(start: int, end: int) -> int:
        return prefix[end] - prefix[start]

    for requested_lines in range(minimum_lines, max_lines + 1):
        target_total = total_width

        @lru_cache(maxsize=None)
        def solve(
            start: int,
            remaining_lines: int,
        ) -> tuple[int, tuple[tuple[int, int], ...]] | None:
            if remaining_lines == 1:
                final_width = width(start, len(tokens))
                if final_width > line_width:
                    return None
                raggedness = (final_width * requested_lines - target_total) ** 2 // (
                    requested_lines * requested_lines
                )
                return raggedness, ((start, len(tokens)),)

            best = None
            minimum_remaining_tokens = remaining_lines - 1
            last_end = len(tokens) - minimum_remaining_tokens
            for end in range(start + 1, last_end + 1):
                current_width = width(start, end)
                if current_width > line_width:
                    break
                if not _valid_break(tokens, end):
                    continue
                remaining_width = width(end, len(tokens))
                if remaining_width > line_width * (remaining_lines - 1):
                    continue
                tail = solve(end, remaining_lines - 1)
                if tail is None:
                    continue
                penalty = _break_penalty(tokens[end - 1].text)
                if character_offsets[end] in preferred_break_offsets:
                    penalty = min(penalty, 60)
                raggedness = (current_width * requested_lines - target_total) ** 2 // (
                    requested_lines * requested_lines
                )
                cost = penalty + raggedness + tail[0]
                candidate = (cost, ((start, end), *tail[1]))
                if best is None or candidate < best:
                    best = candidate
            return best

        solution = solve(0, requested_lines)
        if solution is not None:
            return solution[1]

    raise ChineseLayoutError(
        f"text needs more than {max_lines} lines at {line_width} cells"
    )


def _original_break_offsets(text: str) -> frozenset[int]:
    lines = text.splitlines()
    offsets = set()
    current = 0
    for index, line in enumerate(lines):
        content = line if index == 0 else line.lstrip("　 ")
        current += len(content)
        if index < len(lines) - 1:
            offsets.add(current)
    return frozenset(offsets)


def reflow_chinese_dialogue(
    text: str,
    *,
    protected_terms: Iterable[str] = (),
    line_width: int = DEFAULT_LINE_WIDTH,
    max_lines: int = DEFAULT_MAX_LINES,
) -> ReflowResult:
    """Reflow one dialogue while preserving layout-sensitive cards/lists."""

    if not text:
        raise ChineseLayoutError("dialogue text must not be empty")
    if line_width <= 0 or max_lines <= 0:
        raise ChineseLayoutError("line_width and max_lines must be positive")

    if text.startswith(("　", " ")):
        return ReflowResult(
            original=text,
            text=text,
            preserved_reason="leading_alignment",
            line_widths=dialogue_line_widths(
                text,
                protected_terms=protected_terms,
            ),
        )
    if _SEPARATE_QUOTED_LINES.search(text):
        return ReflowResult(
            original=text,
            text=text,
            preserved_reason="separate_quoted_lines",
            line_widths=dialogue_line_widths(
                text,
                protected_terms=protected_terms,
            ),
        )

    logical = logical_dialogue_text(text)
    tokens = tokenize_dialogue(logical, protected_terms=protected_terms)
    partitions = _partition_tokens(
        tokens,
        line_width=line_width,
        max_lines=max_lines,
        preferred_break_offsets=_original_break_offsets(text),
    )
    lines = [
        "".join(token.text for token in tokens[start:end]) for start, end in partitions
    ]
    reflowed = ("\n" + CONTINUATION_INDENT).join(lines)
    if logical_dialogue_text(reflowed) != logical:
        raise AssertionError("Chinese reflow changed dialogue content")
    widths = dialogue_line_widths(
        reflowed,
        protected_terms=protected_terms,
    )
    if len(widths) > max_lines or max(widths, default=0) > line_width:
        raise AssertionError("Chinese reflow violated its layout bounds")
    return ReflowResult(
        original=text,
        text=reflowed,
        preserved_reason="",
        line_widths=widths,
    )
