"""Deterministic Chinese dialogue reflow for the SRWZ message window."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Sequence

from .text import RUNTIME_FORMAT_TOKEN


# Continuation lines gain one full-width ideographic-space indent at writeback.
# The production story-dialogue profile therefore gives the first line 21
# content cells and continuation lines 20 content cells, keeping every visible
# line inside the same 21-cell boundary after indentation is rendered.
DEFAULT_LINE_WIDTH = 21
DEFAULT_CONTINUATION_LINE_WIDTH = 20
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
_LATIN_TERM = re.compile(r"[A-Za-z0-9]+(?:[.·_-][A-Za-z0-9]+)* ?")
_NUMBER_WITH_UNIT = re.compile(
    r"(?:第[0-9０-９]+(?:话|章|关|幕|次|号|代|阶段|批)?|"
    r"[0-9０-９]+(?:[.,][0-9０-９]+)*(?:%|％|岁|年|月|日|时|分|秒|"
    r"米|公里|千米|海里|节|话|号|机|艘|人|倍|层|级|点|个)?)"
)
_SEPARATE_QUOTED_LINES = re.compile(r"”\n[　 ]*“")

_STRONG_BREAK_END = frozenset("。！？!?")
_CLAUSE_BREAK_END = frozenset("，、；：,;:")
_WEAK_BREAK_END = frozenset("…—")
_CLOSING_PUNCTUATION = frozenset("，。！？；：、,.!?;:％%”’）》】〕〉」』…—")
_OPENING_PUNCTUATION = frozenset("“‘（《【〔〈「『")
_MODAL_PARTICLES = frozenset("啊呀呢吗吧嘛么啦哟哦")
FORBIDDEN_LINE_START_CHARACTERS = _CLOSING_PUNCTUATION
FORBIDDEN_LINE_END_CHARACTERS = _OPENING_PUNCTUATION
DISCOURAGED_LINE_START_CHARACTERS = _MODAL_PARTICLES


class ChineseLayoutError(ValueError):
    """A dialogue string cannot fit the configured Chinese layout."""


@dataclass(frozen=True)
class LayoutWeights:
    """Adjustable costs used to choose among legal Chinese line breaks."""

    strong_break: int = 0
    weak_break: int = 25
    clause_break: int = 40
    arbitrary_break: int = 400
    manual_break_max: int = 60
    raggedness: int = 1
    discouraged_start: int = 180
    short_line_per_cell: int = 0


@dataclass(frozen=True)
class ChineseLayoutProfile:
    """One renderer surface's width, line-count, and scoring contract."""

    profile_id: str
    maximum_width: int
    first_line_maximum_width: int | None
    maximum_lines: int | None
    line_count_mode: str
    line_packing: str = "balanced"
    continuation_indent: str = ""
    minimum_line_width: int = 0
    allow_oversized_token_split: bool = False
    unbroken_terms: tuple[str, ...] = ()
    weights: LayoutWeights = LayoutWeights()

    def __post_init__(self) -> None:
        if not self.profile_id:
            raise ChineseLayoutError("layout profile id must not be empty")
        if self.maximum_width <= 0:
            raise ChineseLayoutError("layout profile width must be positive")
        if (
            self.first_line_maximum_width is not None
            and self.first_line_maximum_width < self.maximum_width
        ):
            raise ChineseLayoutError(
                "layout profile first-line width must not be narrower"
            )
        if self.maximum_lines is not None and self.maximum_lines <= 0:
            raise ChineseLayoutError("layout profile maximum lines must be positive")
        if self.line_count_mode not in {"minimum", "exact", "preserve"}:
            raise ChineseLayoutError(
                f"unsupported line-count mode: {self.line_count_mode}"
            )
        if self.line_packing not in {"balanced", "fill"}:
            raise ChineseLayoutError(
                f"unsupported line-packing mode: {self.line_packing}"
            )
        if not 0 <= self.minimum_line_width <= self.maximum_width:
            raise ChineseLayoutError("layout profile minimum width is invalid")


def load_layout_profiles(path: Path) -> dict[str, ChineseLayoutProfile]:
    """Load the checked-in, dependency-free Chinese layout profile set."""

    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_version") != 1:
        raise ChineseLayoutError(f"unsupported layout profile schema: {path}")
    default_weights = document.get("default_weights")
    common_unbroken_terms = document.get("common_unbroken_terms", [])
    rows = document.get("profiles")
    if not isinstance(default_weights, dict) or not isinstance(rows, dict):
        raise ChineseLayoutError(f"malformed layout profile document: {path}")
    if (
        not isinstance(common_unbroken_terms, list)
        or any(
            not isinstance(term, str) or len(term) < 2 or "\n" in term
            for term in common_unbroken_terms
        )
        or len(common_unbroken_terms) != len(set(common_unbroken_terms))
    ):
        raise ChineseLayoutError(f"malformed common unbroken terms: {path}")
    allowed_weight_keys = set(LayoutWeights.__dataclass_fields__)
    unknown_default_weights = set(default_weights) - allowed_weight_keys
    if unknown_default_weights:
        raise ChineseLayoutError(
            f"unknown default layout weights: {sorted(unknown_default_weights)}"
        )
    result = {}
    for profile_id, raw in rows.items():
        if not isinstance(profile_id, str) or not isinstance(raw, dict):
            raise ChineseLayoutError(f"malformed layout profile row: {profile_id!r}")
        raw_weights = raw.get("weights", {})
        if not isinstance(raw_weights, dict):
            raise ChineseLayoutError(f"malformed layout weights: {profile_id}")
        profile_unbroken_terms = raw.get("unbroken_terms", [])
        if not isinstance(profile_unbroken_terms, list) or any(
            not isinstance(term, str) or len(term) < 2 or "\n" in term
            for term in profile_unbroken_terms
        ):
            raise ChineseLayoutError(f"malformed unbroken terms for {profile_id}")
        unknown_weights = set(raw_weights) - allowed_weight_keys
        if unknown_weights:
            raise ChineseLayoutError(
                f"unknown layout weights for {profile_id}: {sorted(unknown_weights)}"
            )
        weights = LayoutWeights(**{**default_weights, **raw_weights})
        try:
            result[profile_id] = ChineseLayoutProfile(
                profile_id=profile_id,
                maximum_width=int(raw["maximum_width"]),
                first_line_maximum_width=(
                    None
                    if raw.get("first_line_maximum_width") is None
                    else int(raw["first_line_maximum_width"])
                ),
                maximum_lines=(
                    None
                    if raw.get("maximum_lines") is None
                    else int(raw["maximum_lines"])
                ),
                line_count_mode=str(raw.get("line_count_mode", "minimum")),
                line_packing=str(raw.get("line_packing", "balanced")),
                continuation_indent=str(raw.get("continuation_indent", "")),
                minimum_line_width=int(raw.get("minimum_line_width", 0)),
                allow_oversized_token_split=bool(
                    raw.get("allow_oversized_token_split", False)
                ),
                unbroken_terms=tuple(
                    dict.fromkeys((*common_unbroken_terms, *profile_unbroken_terms))
                ),
                weights=weights,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ChineseLayoutError(
                f"malformed layout profile: {profile_id}"
            ) from error
    if not result:
        raise ChineseLayoutError("layout profile document is empty")
    return result


def load_release_protected_terms(
    release_path: Path,
    *,
    project_root: Path,
) -> tuple[str, ...]:
    """Load canonical multi-character terms used as soft layout atoms."""

    release = json.loads(release_path.read_text(encoding="utf-8"))
    if not isinstance(release, dict):
        raise ChineseLayoutError(
            f"release document is not an object: {release_path}"
        )
    terms = set()
    for raw_path in release.get("glossary_sources", ()):
        glossary_path = (project_root / str(raw_path)).resolve()
        glossary = json.loads(glossary_path.read_text(encoding="utf-8"))
        if not isinstance(glossary, dict):
            raise ChineseLayoutError(
                f"glossary document is not an object: {glossary_path}"
            )
        for term in glossary.get("terms", ()):
            if not isinstance(term, dict):
                continue
            translation = term.get("translation")
            if isinstance(translation, str) and len(translation) > 1:
                terms.add(translation)
    return tuple(sorted(terms, key=lambda term: (-len(term), term)))


@dataclass(frozen=True)
class LayoutToken:
    text: str
    width: int
    atomic: bool = False


@dataclass(frozen=True)
class StageKeywordLinkSpan:
    """One balanced native STAGE keyword span in decoded semantic notation."""

    text: str
    body: str
    start: int
    end: int


def stage_keyword_link_spans(text: str) -> tuple[StageKeywordLinkSpan, ...]:
    """Parse balanced ``《body》`` spans used for STAGE keyword controls."""

    spans = []
    opened_at = None
    for index, character in enumerate(text):
        if character == "《":
            if opened_at is not None:
                raise ChineseLayoutError(
                    f"nested STAGE keyword start at character {index}"
                )
            opened_at = index
        elif character == "》":
            if opened_at is None:
                raise ChineseLayoutError(
                    f"unmatched STAGE keyword end at character {index}"
                )
            if index == opened_at + 1:
                raise ChineseLayoutError("empty STAGE keyword span")
            end = index + 1
            spans.append(
                StageKeywordLinkSpan(
                    text=text[opened_at:end],
                    body=text[opened_at + 1 : index],
                    start=opened_at,
                    end=end,
                )
            )
            opened_at = None
    if opened_at is not None:
        raise ChineseLayoutError(
            f"unmatched STAGE keyword start at character {opened_at}"
        )
    return tuple(spans)


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
    stage_keyword_links: bool = False,
) -> tuple[LayoutToken, ...]:
    """Split text into renderer-width units without splitting names/tokens."""

    terms = _normalize_protected_terms(
        (*tuple(protected_terms), *COMMON_PROTECTED_WORDS)
    )
    term_index = _protected_term_index(terms)
    keyword_links_by_start = (
        {span.start: span for span in stage_keyword_link_spans(text)}
        if stage_keyword_links
        else {}
    )
    tokens = []
    offset = 0
    while offset < len(text):
        keyword_link = keyword_links_by_start.get(offset)
        if keyword_link is not None:
            body_width = sum(
                token.width
                for token in tokenize_dialogue(
                    keyword_link.body,
                    protected_terms=terms,
                    stage_keyword_links=False,
                )
            )
            tokens.append(
                LayoutToken(
                    keyword_link.text,
                    body_width,
                    atomic=True,
                )
            )
            offset = keyword_link.end
            continue
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
        # Paired quotation and title marks obey opening/closing punctuation
        # rules but do not make the entire enclosed phrase indivisible.  Long
        # quoted titles must still wrap inside narrow dialogue/LIBRARY boxes.
        for pattern in (_NUMBER_WITH_UNIT, _LATIN_TERM):
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
    stage_keyword_links: bool = False,
) -> int:
    """Return fixed-cell width, expanding runtime string placeholders."""

    content = text.lstrip("　 ")
    return sum(
        token.width
        for token in tokenize_dialogue(
            content,
            protected_terms=protected_terms,
            stage_keyword_links=stage_keyword_links,
        )
    )


def dialogue_line_widths(
    text: str,
    *,
    protected_terms: Iterable[str] = (),
    stage_keyword_links: bool = False,
) -> tuple[int, ...]:
    return tuple(
        rendered_line_width(
            line,
            protected_terms=protected_terms,
            stage_keyword_links=stage_keyword_links,
        )
        for line in text.splitlines()
    )


def _valid_break(tokens: Sequence[LayoutToken], index: int) -> bool:
    """Apply the strict CLReq/UAX #14 punctuation prohibitions."""

    previous = tokens[index - 1].text
    following = tokens[index].text
    if previous[-1] in _OPENING_PUNCTUATION:
        return False
    if following[0] in _CLOSING_PUNCTUATION:
        return False
    return True


def _break_penalty(
    previous: str,
    following: str,
    *,
    weights: LayoutWeights,
) -> int:
    last = previous[-1]
    if last in _STRONG_BREAK_END:
        penalty = weights.strong_break
    elif last in _WEAK_BREAK_END:
        penalty = weights.weak_break
    elif last in _CLAUSE_BREAK_END:
        penalty = weights.clause_break
    else:
        penalty = weights.arbitrary_break
    if following[0] in _MODAL_PARTICLES and last not in _STRONG_BREAK_END:
        penalty += weights.discouraged_start
    return penalty


def _split_oversized_tokens(
    tokens: Sequence[LayoutToken],
    *,
    line_width: int,
    allow_split: bool,
) -> tuple[LayoutToken, ...]:
    """Split an overlong prose token only for profiles that allow it."""

    output = []
    for token in tokens:
        if token.width <= line_width:
            output.append(token)
            continue
        if (
            token.atomic
            or not allow_split
            or token.text.startswith(("$", "%", "{", "<"))
        ):
            raise ChineseLayoutError(
                f"indivisible term exceeds {line_width} cells: {token.text!r}"
            )
        # Long book titles and Latin phrases may exceed narrow LIBRARY columns.
        # Retokenize them as display characters while keeping paired leaders
        # and dashes atomic.
        offset = 0
        while offset < len(token.text):
            if token.text.startswith(("……", "——"), offset):
                output.append(LayoutToken(token.text[offset : offset + 2], 2))
                offset += 2
            else:
                output.append(LayoutToken(token.text[offset], 1))
                offset += 1
    return tuple(output)


def _partition_tokens(
    tokens: Sequence[LayoutToken],
    *,
    line_width: int,
    first_line_width: int | None,
    max_lines: int,
    exact_lines: int | None = None,
    line_packing: str = "balanced",
    preferred_break_offsets: frozenset[int] = frozenset(),
    weights: LayoutWeights = LayoutWeights(),
    minimum_line_width: int = 0,
) -> tuple[tuple[int, int], ...]:
    if not tokens:
        return ((0, 0),)
    if line_packing not in {"balanced", "fill"}:
        raise ChineseLayoutError(f"unsupported line-packing mode: {line_packing}")

    prefix = [0]
    character_offsets = [0]
    for token in tokens:
        prefix.append(prefix[-1] + token.width)
        character_offsets.append(character_offsets[-1] + len(token.text))
    total_width = prefix[-1]
    first_line_width = first_line_width or line_width
    minimum_lines = (
        1
        if total_width <= first_line_width
        else 1 + (total_width - first_line_width + line_width - 1) // line_width
    )

    def width(start: int, end: int) -> int:
        return prefix[end] - prefix[start]

    if exact_lines is not None:
        if not minimum_lines <= exact_lines <= max_lines:
            raise ChineseLayoutError(
                f"text cannot use exactly {exact_lines} lines at {line_width} cells"
            )
        requested_line_counts = (exact_lines,)
    else:
        requested_line_counts = range(minimum_lines, max_lines + 1)

    def line_cost(
        current_width: int,
        requested_lines: int,
        current_line: int,
        current_limit: int,
    ) -> int:
        if line_packing == "fill":
            # Wide scrolling prose should use the available row before it
            # wraps, but a natural/manual breakpoint may still beat squeezing
            # in the final one or two cells.  Do not penalize the last line:
            # its width is simply what remains after the earlier rows.
            raggedness = (
                0
                if current_line == requested_lines - 1
                else (current_limit - current_width) ** 2
            )
        else:
            raggedness = (current_width * requested_lines - total_width) ** 2 // (
                requested_lines * requested_lines
            )
        shortfall = max(0, minimum_line_width - current_width)
        return raggedness * weights.raggedness + shortfall * weights.short_line_per_cell

    for requested_lines in requested_line_counts:

        @lru_cache(maxsize=None)
        def solve(
            start: int,
            remaining_lines: int,
        ) -> tuple[int, tuple[tuple[int, int], ...]] | None:
            current_line = requested_lines - remaining_lines
            current_limit = first_line_width if current_line == 0 else line_width
            if remaining_lines == 1:
                final_width = width(start, len(tokens))
                if final_width > current_limit:
                    return None
                if (
                    line_packing == "fill"
                    and requested_lines > 1
                    and final_width < minimum_line_width
                ):
                    return None
                return (
                    line_cost(
                        final_width,
                        requested_lines,
                        current_line,
                        current_limit,
                    ),
                    ((start, len(tokens)),),
                )

            best = None
            minimum_remaining_tokens = remaining_lines - 1
            last_end = len(tokens) - minimum_remaining_tokens
            for end in range(start + 1, last_end + 1):
                current_width = width(start, end)
                if current_width > current_limit:
                    break
                if not _valid_break(tokens, end):
                    continue
                remaining_width = width(end, len(tokens))
                if remaining_width > line_width * (remaining_lines - 1):
                    continue
                if (
                    line_packing == "fill"
                    and remaining_width
                    < minimum_line_width * (remaining_lines - 1)
                ):
                    continue
                tail = solve(end, remaining_lines - 1)
                if tail is None:
                    continue
                penalty = _break_penalty(
                    tokens[end - 1].text,
                    tokens[end].text,
                    weights=weights,
                )
                if character_offsets[end] in preferred_break_offsets:
                    penalty = min(penalty, weights.manual_break_max)
                cost = (
                    penalty
                    + line_cost(
                        current_width,
                        requested_lines,
                        current_line,
                        current_limit,
                    )
                    + tail[0]
                )
                candidate = (cost, ((start, end), *tail[1]))
                if best is None or candidate < best:
                    best = candidate
            return best

        solution = solve(0, requested_lines)
        if solution is not None:
            return solution[1]

    if exact_lines is not None:
        raise ChineseLayoutError(
            f"text has no legal {exact_lines}-line layout at {line_width} cells"
        )
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


def partition_chinese_text(
    text: str,
    *,
    protected_terms: Iterable[str] = (),
    line_width: int,
    first_line_width: int | None = None,
    max_lines: int,
    exact_lines: int | None = None,
    line_packing: str = "balanced",
    preferred_break_offsets: frozenset[int] = frozenset(),
    weights: LayoutWeights = LayoutWeights(),
    minimum_line_width: int = 0,
    allow_oversized_token_split: bool = False,
    stage_keyword_links: bool = False,
) -> tuple[str, ...]:
    """Partition one logical Chinese string without adding indentation."""

    if not text or "\n" in text or "\r" in text:
        raise ChineseLayoutError("partition input must be one non-empty logical line")
    if line_width <= 0 or max_lines <= 0:
        raise ChineseLayoutError("line_width and max_lines must be positive")
    tokens = _split_oversized_tokens(
        tokenize_dialogue(
            text,
            protected_terms=protected_terms,
            stage_keyword_links=stage_keyword_links,
        ),
        line_width=max(line_width, first_line_width or line_width),
        allow_split=allow_oversized_token_split,
    )
    partitions = _partition_tokens(
        tokens,
        line_width=line_width,
        first_line_width=first_line_width,
        max_lines=max_lines,
        exact_lines=exact_lines,
        line_packing=line_packing,
        preferred_break_offsets=preferred_break_offsets,
        weights=weights,
        minimum_line_width=minimum_line_width,
    )
    lines = tuple(
        "".join(token.text for token in tokens[start:end]) for start, end in partitions
    )
    if "".join(lines) != text:
        raise AssertionError("Chinese partition changed logical text")
    return lines


def reflow_chinese_paragraph(
    text: str,
    *,
    profile: ChineseLayoutProfile,
    protected_terms: Iterable[str] = (),
    exact_lines: int | None = None,
    preferred_break_offsets: frozenset[int] = frozenset(),
) -> ReflowResult:
    """Lay out one logical prose paragraph using a named surface profile."""

    if not text or "\n" in text or "\r" in text:
        raise ChineseLayoutError("paragraph input must be one non-empty logical line")
    if profile.line_count_mode in {"exact", "preserve"} and exact_lines is None:
        raise ChineseLayoutError(f"{profile.profile_id} requires an exact line count")
    if profile.line_count_mode == "minimum" and exact_lines is not None:
        raise ChineseLayoutError(
            f"{profile.profile_id} does not accept an exact line count"
        )
    maximum_lines = profile.maximum_lines
    if maximum_lines is None:
        # One display cell per line is a deliberately loose, finite ceiling.
        maximum_lines = max(
            1,
            rendered_line_width(
                text,
                protected_terms=protected_terms,
                stage_keyword_links=False,
            ),
        )
    effective_protected_terms = (*profile.unbroken_terms, *protected_terms)
    lines = partition_chinese_text(
        text,
        protected_terms=effective_protected_terms,
        line_width=profile.maximum_width,
        first_line_width=profile.first_line_maximum_width,
        max_lines=maximum_lines,
        exact_lines=exact_lines,
        line_packing=profile.line_packing,
        preferred_break_offsets=preferred_break_offsets,
        weights=profile.weights,
        minimum_line_width=profile.minimum_line_width,
        allow_oversized_token_split=profile.allow_oversized_token_split,
        stage_keyword_links=False,
    )
    result = "\n".join(lines)
    widths = dialogue_line_widths(
        result,
        protected_terms=effective_protected_terms,
        stage_keyword_links=False,
    )
    return ReflowResult(
        original=text,
        text=result,
        preserved_reason="",
        line_widths=widths,
    )


def reflow_chinese_dialogue(
    text: str,
    *,
    protected_terms: Iterable[str] = (),
    line_width: int = DEFAULT_LINE_WIDTH,
    max_lines: int = DEFAULT_MAX_LINES,
    profile: ChineseLayoutProfile | None = None,
    stage_keyword_links: bool = False,
) -> ReflowResult:
    """Reflow one dialogue while preserving layout-sensitive cards/lists."""

    if not text:
        raise ChineseLayoutError("dialogue text must not be empty")
    if profile is not None:
        line_width = profile.maximum_width
        first_line_width = profile.first_line_maximum_width
        if profile.maximum_lines is None:
            raise ChineseLayoutError("dialogue profile must have a maximum line count")
        max_lines = profile.maximum_lines
        weights = profile.weights
        minimum_line_width = profile.minimum_line_width
        continuation_indent = profile.continuation_indent
        allow_oversized_token_split = profile.allow_oversized_token_split
        protected_terms = (*profile.unbroken_terms, *protected_terms)
    else:
        weights = LayoutWeights()
        first_line_width = None
        minimum_line_width = 0
        continuation_indent = CONTINUATION_INDENT
        allow_oversized_token_split = False
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
                stage_keyword_links=stage_keyword_links,
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
                stage_keyword_links=stage_keyword_links,
            ),
        )

    logical = logical_dialogue_text(text)
    lines = partition_chinese_text(
        logical,
        protected_terms=protected_terms,
        line_width=line_width,
        first_line_width=first_line_width,
        max_lines=max_lines,
        line_packing=(profile.line_packing if profile is not None else "balanced"),
        preferred_break_offsets=_original_break_offsets(text),
        weights=weights,
        minimum_line_width=minimum_line_width,
        allow_oversized_token_split=allow_oversized_token_split,
        stage_keyword_links=stage_keyword_links,
    )
    reflowed = ("\n" + continuation_indent).join(lines)
    if logical_dialogue_text(reflowed) != logical:
        raise AssertionError("Chinese reflow changed dialogue content")
    widths = dialogue_line_widths(
        reflowed,
        protected_terms=protected_terms,
        stage_keyword_links=stage_keyword_links,
    )
    first_limit = first_line_width or line_width
    if (
        len(widths) > max_lines
        or (widths and widths[0] > first_limit)
        or any(width > line_width for width in widths[1:])
    ):
        raise AssertionError("Chinese reflow violated its layout bounds")
    return ReflowResult(
        original=text,
        text=reflowed,
        preserved_reason="",
        line_widths=widths,
    )


def fit_chinese_dialogue_layout(
    text: str,
    *,
    protected_terms: Iterable[str] = (),
    line_width: int = DEFAULT_LINE_WIDTH,
    max_lines: int = DEFAULT_MAX_LINES,
    profile: ChineseLayoutProfile | None = None,
    stage_keyword_links: bool = False,
) -> ReflowResult:
    """Preserve valid manual breaks, otherwise reflow without deleting text."""

    protected_terms = tuple(protected_terms)
    if profile is not None:
        line_width = profile.maximum_width
        if profile.maximum_lines is None:
            raise ChineseLayoutError(
                "dialogue profile must have a maximum line count"
            )
        max_lines = profile.maximum_lines
        first_line_width = profile.first_line_maximum_width or line_width
        effective_terms = (*profile.unbroken_terms, *protected_terms)
    else:
        first_line_width = line_width
        effective_terms = protected_terms
    widths = dialogue_line_widths(
        text,
        protected_terms=effective_terms,
        stage_keyword_links=stage_keyword_links,
    )
    if (
        len(widths) <= max_lines
        and (not widths or widths[0] <= first_line_width)
        and all(width <= line_width for width in widths[1:])
    ):
        return ReflowResult(
            original=text,
            text=text,
            preserved_reason="already_fits",
            line_widths=widths,
        )

    result = reflow_chinese_dialogue(
        text,
        protected_terms=protected_terms,
        line_width=line_width,
        max_lines=max_lines,
        profile=profile,
        stage_keyword_links=stage_keyword_links,
    )
    if (
        len(result.line_widths) > max_lines
        or (
            result.line_widths
            and result.line_widths[0] > first_line_width
        )
        or any(width > line_width for width in result.line_widths[1:])
    ):
        raise ChineseLayoutError(
            f"dialogue cannot fit {line_width}x{max_lines}: "
            f"{result.line_widths!r}"
        )
    return ReflowResult(
        original=result.original,
        text=result.text,
        preserved_reason="reflowed_to_fit",
        line_widths=result.line_widths,
    )
