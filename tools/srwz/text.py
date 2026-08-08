"""Strict SRWZ text decoding shared by menu, story and summary parsers."""

from __future__ import annotations

import json
import re
import string
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Optional


PRINTABLE_ASCII = frozenset(
    "".join((string.digits, string.ascii_letters, string.punctuation, " "))
)
ORIGINAL_FULLWIDTH_ASCII = frozenset(string.digits + string.ascii_letters)
RUNTIME_FORMAT_TOKEN = re.compile(r"%(?:\d+\$)?[diouxXeEfFgGcrsa]")
RUNTIME_SUBSTITUTION_TOKEN = re.compile(r"\$[cflnF]")
CONTROL_NOTATION = re.compile(
    rf"{RUNTIME_SUBSTITUTION_TOKEN.pattern}"
    rf"|{RUNTIME_FORMAT_TOKEN.pattern}"
    r"|\{[0-9A-Fa-f]{2}\}"
    r"|@?<[A-Za-z0-9_]+:[0-9A-Fa-f]{2}>"
)
POTENTIAL_CONTROL_NOTATION_START = re.compile(
    r"%(?=[-+#0.*$0-9A-Za-z])"
    r"|\$(?=[A-Za-z])"
    r"|@?<(?=[A-Za-z0-9_])"
    r"|\{(?=[0-9A-Za-z]{2}\})"
)


class SrwzTextError(ValueError):
    """A malformed or unterminated SRWZ text string."""

    def __init__(self, message: str, *, offset: int):
        self.offset = offset
        super().__init__(f"{message} at input offset 0x{offset:X}")


class SrwzTextEncodeError(ValueError):
    """A source string contains a token or character that cannot be encoded."""

    def __init__(self, message: str, *, character_index: int):
        self.character_index = character_index
        super().__init__(f"{message} at character index {character_index}")


@dataclass(frozen=True)
class ControlNotationToken:
    """One non-glyph token in the lossless decoded-text notation."""

    kind: str
    text: str
    start: int
    end: int


@dataclass(frozen=True)
class TextTable:
    characters: Mapping[int, str]
    tags: Mapping[int, str]
    inverse_characters: Mapping[str, int] = field(init=False, repr=False)
    inverse_tags: Mapping[str, int] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        characters = dict(self.characters)
        tags = dict(self.tags)
        object.__setattr__(
            self,
            "characters",
            MappingProxyType(characters),
        )
        object.__setattr__(
            self,
            "tags",
            MappingProxyType(tags),
        )
        inverse_characters = {}
        for encoded, character in sorted(characters.items()):
            inverse_characters.setdefault(character, encoded)
        object.__setattr__(
            self,
            "inverse_characters",
            MappingProxyType(inverse_characters),
        )
        object.__setattr__(
            self,
            "inverse_tags",
            MappingProxyType({name: encoded for encoded, name in tags.items()}),
        )


@dataclass(frozen=True)
class DecodedText:
    text: str
    start: int
    end: int
    terminator: str
    unknown_code_count: int = 0

    @property
    def consumed(self) -> int:
        return self.end - self.start


def _load_relaxed_json(path: Path) -> object:
    """Load the pinned table, accepting its single JSON5 trailing comma."""

    source = path.read_text(encoding="utf-8")
    normalized = re.sub(r",(\s*[}\]])", r"\1", source)
    return json.loads(normalized)


def load_text_table(path: Path) -> TextTable:
    raw = _load_relaxed_json(path)
    if not isinstance(raw, dict):
        raise ValueError("text table root must be an object")
    raw_characters = raw.get("tbl")
    raw_tags = raw.get("tags")
    if not isinstance(raw_characters, dict) or not isinstance(raw_tags, dict):
        raise ValueError("text table must contain tbl and tags objects")

    characters = {}
    for encoded, character in raw_characters.items():
        if not isinstance(encoded, str) or not isinstance(character, str):
            raise ValueError("text table entries must map strings to strings")
        value = int(encoded, 16)
        if not 0 <= value <= 0xFFFF:
            raise ValueError(f"text code out of range: {encoded}")
        characters[value] = character

    tags = {}
    for encoded, name in raw_tags.items():
        if not isinstance(encoded, str) or not isinstance(name, str):
            raise ValueError("tag entries must map strings to strings")
        value = int(encoded, 0)
        if not 0 <= value <= 0xFF:
            raise ValueError(f"tag code out of range: {encoded}")
        tags[value] = name

    return TextTable(characters=characters, tags=tags)


def original_fullwidth_ascii_overrides(table: TextTable) -> dict[str, int]:
    """Route visible ASCII through the original game's two-byte glyphs.

    The SRWZ dialogue and intermission renderers consume visible text as
    two-byte codes.  Raw one-byte ASCII therefore cannot safely be used for
    labels such as ``ZAFT``, ``PLANT``, ``LS`` or ``WM``: adjacent bytes can
    be interpreted as one unrelated code.  The stock table already exposes
    the game's Latin, digit and punctuation glyphs through Shift-JIS-style
    fullwidth codes.  Return the alphanumeric codes under their ASCII
    identities so the corpus remains ordinary ASCII while the stored payload
    stays two-byte.  Punctuation is deliberately left to the localized font
    codebook because Chinese and ASCII punctuation are not interchangeable.

    Runtime substitution/format tokens are still emitted byte-for-byte by
    :func:`encode_text` before overrides are consulted.
    """

    overrides: dict[str, int] = {}
    for character in sorted(ORIGINAL_FULLWIDTH_ASCII):
        source_character = chr(ord(character) + 0xFEE0)
        code = table.inverse_characters.get(source_character)
        if code is None or code < 0x8000:
            raise ValueError(
                "original fullwidth ASCII code is absent for "
                f"{character!r} via {source_character!r}"
            )
        overrides[character] = code
    return overrides


def normalize_original_fullwidth_ascii(text: str) -> str:
    """Canonicalize stock fullwidth Latin/digits to corpus ASCII identity."""

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    return "".join(
        chr(ord(character) - 0xFEE0)
        if (
            "０" <= character <= "９"
            or "Ａ" <= character <= "Ｚ"
            or "ａ" <= character <= "ｚ"
        )
        else character
        for character in text
    )


def decode_text(
    data: bytes,
    offset: int,
    table: TextTable,
    *,
    stop_at_newline: bool = False,
    end: Optional[int] = None,
    allow_end: bool = False,
) -> DecodedText:
    """Decode one terminated SRWZ string without reading outside its bounds."""

    limit = len(data) if end is None else end
    if not 0 <= offset <= limit <= len(data):
        raise ValueError("text decode bounds are outside the input")

    current = offset
    parts = []
    unknown_code_count = 0

    def read_parameter(context: str) -> int:
        nonlocal current
        if current >= limit:
            raise SrwzTextError(f"truncated {context}", offset=current)
        value = data[current]
        current += 1
        return value

    while current < limit:
        code = data[current]
        current += 1

        if code == 0:
            return DecodedText(
                text="".join(parts),
                start=offset,
                end=current,
                terminator="nul",
                unknown_code_count=unknown_code_count,
            )

        if code == 0x0A:
            if stop_at_newline:
                return DecodedText(
                    text="".join(parts),
                    start=offset,
                    end=current,
                    terminator="newline",
                    unknown_code_count=unknown_code_count,
                )
            parts.append("\n")
            continue

        if 0x31 <= code <= 0x35:
            parameter = read_parameter("text tag")
            name = table.tags.get(code, f"{code:02X}")
            parts.append(f"<{name}:{parameter:02X}>")
            continue

        if 0x80 <= code <= 0x9F or 0xE0 <= code <= 0xEA:
            second = read_parameter("two-byte text code")
            encoded = (code << 8) | second
            character = table.characters.get(encoded)
            if character is None:
                parts.append(f"{{{code:02X}}}{{{second:02X}}}")
                unknown_code_count += 1
            else:
                parts.append(character)
            continue

        character = chr(code)
        if character in PRINTABLE_ASCII:
            parts.append(character)
            continue

        if 0xA0 < code < 0xE0:
            try:
                parts.append(bytes([code]).decode("cp932"))
            except UnicodeDecodeError:
                parts.append(f"{{{code:02X}}}")
                unknown_code_count += 1
            continue

        parts.append(f"{{{code:02X}}}")
        unknown_code_count += 1

    if allow_end:
        return DecodedText(
            text="".join(parts),
            start=offset,
            end=current,
            terminator="end",
            unknown_code_count=unknown_code_count,
        )
    raise SrwzTextError("unterminated text", offset=current)


def _inverse_characters(
    table: TextTable,
    overrides: Optional[Mapping[str, int]] = None,
) -> Mapping[str, int]:
    if not overrides:
        return table.inverse_characters
    inverse = dict(table.inverse_characters)
    for character, encoded in overrides.items():
        if not isinstance(character, str) or len(character) != 1:
            raise ValueError("text encoding overrides need one character")
        if not 0 <= encoded <= 0xFFFF:
            raise ValueError("text encoding override is outside two bytes")
        inverse[character] = encoded
    return inverse


def control_notation_tokens(text: str) -> tuple[ControlNotationToken, ...]:
    """Classify placeholders and control notation without splitting them."""

    if not isinstance(text, str):
        raise TypeError("control notation source must be a string")
    tokens = []
    for match in CONTROL_NOTATION.finditer(text):
        token = match.group(0)
        if RUNTIME_FORMAT_TOKEN.fullmatch(token):
            kind = "runtime_format"
        elif RUNTIME_SUBSTITUTION_TOKEN.fullmatch(token):
            kind = "runtime_substitution"
        elif token.startswith("{"):
            kind = "raw_byte"
        else:
            kind = "text_tag"
        tokens.append(
            ControlNotationToken(
                kind=kind,
                text=token,
                start=match.start(),
                end=match.end(),
            )
        )
    return tuple(tokens)


def control_notation_positions(text: str) -> frozenset[int]:
    """Return character positions occupied by lossless runtime notation."""

    positions = set()
    for token in control_notation_tokens(text):
        positions.update(range(token.start, token.end))
    return frozenset(positions)


def unrecognized_control_notation_offsets(text: str) -> tuple[int, ...]:
    """Locate placeholder-like syntax not accepted by the strict encoder.

    A literal percentage such as ``30%`` is not suspicious.  A sequence such
    as ``%02d`` or ``$q`` is: silently treating it as visible ASCII would let
    a future runtime placeholder leak into font allocation.
    """

    protected = control_notation_positions(text)
    return tuple(
        match.start()
        for match in POTENTIAL_CONTROL_NOTATION_START.finditer(text)
        if match.start() not in protected
    )


def encode_text(
    text: str,
    table: TextTable,
    *,
    overrides: Optional[Mapping[str, int]] = None,
    terminate: bool = False,
) -> bytes:
    """Encode the decoder's lossless text notation deterministically."""

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    inverse_characters = _inverse_characters(table, overrides)
    inverse_tags = table.inverse_tags
    output = bytearray()
    index = 0

    while index < len(text):
        character = text[index]

        if character == "\n":
            output.append(0x0A)
            index += 1
            continue

        runtime_substitution_match = RUNTIME_SUBSTITUTION_TOKEN.match(text, index)
        if runtime_substitution_match:
            output.extend(runtime_substitution_match.group(0).encode("ascii"))
            index = runtime_substitution_match.end()
            continue

        runtime_format_match = RUNTIME_FORMAT_TOKEN.match(text, index)
        if runtime_format_match:
            output.extend(runtime_format_match.group(0).encode("ascii"))
            index = runtime_format_match.end()
            continue

        raw_match = re.match(r"\{([0-9A-Fa-f]{2})\}", text[index:])
        if raw_match:
            output.append(int(raw_match.group(1), 16))
            index += len(raw_match.group(0))
            continue

        tag_match = re.match(
            r"<([A-Za-z0-9_]+):([0-9A-Fa-f]{2})>",
            text[index:],
        )
        if tag_match:
            tag_name = tag_match.group(1)
            if tag_name in inverse_tags:
                tag = inverse_tags[tag_name]
            elif re.fullmatch(r"[0-9A-Fa-f]{2}", tag_name):
                tag = int(tag_name, 16)
            else:
                raise SrwzTextEncodeError(
                    f"unknown text tag {tag_name!r}",
                    character_index=index,
                )
            output.extend((tag, int(tag_match.group(2), 16)))
            index += len(tag_match.group(0))
            continue

        override_code = overrides.get(character) if overrides is not None else None
        if override_code is not None:
            if character in PRINTABLE_ASCII and override_code == ord(character):
                output.append(override_code)
            else:
                output.extend(override_code.to_bytes(2, "big"))
            index += 1
            continue

        if character in PRINTABLE_ASCII:
            output.append(ord(character))
            index += 1
            continue

        encoded = inverse_characters.get(character)
        if encoded is not None:
            output.extend(encoded.to_bytes(2, "big"))
            index += 1
            continue

        try:
            cp932 = character.encode("cp932")
        except UnicodeEncodeError as error:
            raise SrwzTextEncodeError(
                f"unmapped character {character!r}",
                character_index=index,
            ) from error
        if len(cp932) == 1 and 0xA1 <= cp932[0] <= 0xDF:
            output.extend(cp932)
            index += 1
            continue

        raise SrwzTextEncodeError(
            f"unmapped character {character!r}",
            character_index=index,
        )

    if terminate:
        output.append(0)
    return bytes(output)


def augment_text_table(
    table: TextTable,
    overrides: Mapping[str, int],
) -> TextTable:
    """Return a readback table containing explicit character/code overrides."""

    characters = dict(table.characters)
    for character, code in overrides.items():
        if not isinstance(character, str) or len(character) != 1:
            raise SrwzTextEncodeError(
                "text-table override character must have length one",
                character_index=0,
            )
        if not isinstance(code, int) or not 0 <= code <= 0xFFFF:
            raise SrwzTextEncodeError(
                "text-table override code must fit 16 bits",
                character_index=0,
            )
        previous = characters.get(code)
        if previous is not None and previous != character:
            raise SrwzTextEncodeError(
                f"text-table override collision at code 0x{code:04X}",
                character_index=0,
            )
        characters[code] = character
    return TextTable(characters=characters, tags=table.tags)


def project_runtime_text_table(
    table: TextTable,
    overrides: Mapping[str, int],
) -> TextTable:
    """Project replacement glyph identities onto a runtime decoding table."""

    characters = dict(table.characters)
    seen_codes = {}
    for character, code in overrides.items():
        if (
            not isinstance(character, str)
            or len(character) != 1
            or not isinstance(code, int)
            or isinstance(code, bool)
            or not 0 <= code <= 0xFFFF
        ):
            raise SrwzTextEncodeError(
                "runtime text-table override is invalid",
                character_index=0,
            )
        previous = seen_codes.setdefault(code, character)
        if previous != character:
            raise SrwzTextEncodeError(
                f"runtime text-table override collision at code 0x{code:04X}",
                character_index=0,
            )
        characters[code] = character
    return TextTable(characters=characters, tags=table.tags)


__all__ = [
    "DecodedText",
    "ControlNotationToken",
    "ORIGINAL_FULLWIDTH_ASCII",
    "RUNTIME_FORMAT_TOKEN",
    "RUNTIME_SUBSTITUTION_TOKEN",
    "SrwzTextError",
    "SrwzTextEncodeError",
    "TextTable",
    "augment_text_table",
    "control_notation_positions",
    "control_notation_tokens",
    "decode_text",
    "encode_text",
    "load_text_table",
    "normalize_original_fullwidth_ascii",
    "original_fullwidth_ascii_overrides",
    "project_runtime_text_table",
    "unrecognized_control_notation_offsets",
]
