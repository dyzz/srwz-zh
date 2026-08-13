"""Fail-closed source locks for the v0.2 LIBRARY localization scope.

The sound-select title table is intentionally not a translation surface.
Chinese UI work may rebuild COMPDATA, but the decoded title-table span must
remain byte-for-byte identical to the Japanese source.
"""

from __future__ import annotations

import hashlib
import re
import struct
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from .glossary import apply_glossary_variants
from .text import TextTable, decode_text, encode_text
from .tim2 import scan_tim2


class LibraryScopeError(ValueError):
    """A v0.2 LIBRARY source or preservation lock does not match."""


def compact_source_surface(text: str) -> str:
    """Normalize a Japanese source surface without changing semantic letters."""

    normalized = unicodedata.normalize("NFKC", text)
    return re.sub(r"[\s・\-−－]", "", normalized).lower()


def apply_source_surface_replacements(
    text: str,
    source_text: str,
    config: Mapping[str, object],
) -> tuple[str, list[str]]:
    """Apply a reviewed variant only when its Japanese source is present."""

    compact_source = compact_source_surface(source_text)
    candidate = text
    applied: list[str] = []
    replacements: list[tuple[str, str, str]] = []
    rules = config.get("source_surface_replacements", [])
    if not isinstance(rules, list):
        raise LibraryScopeError("source_surface_replacements must be an array")
    for rule in rules:
        if not isinstance(rule, Mapping):
            raise LibraryScopeError("invalid LIBRARY source-surface replacement")
        source_terms = rule.get("source_terms", [])
        variants = rule.get("from", [])
        target = rule.get("to")
        rule_id = rule.get("id")
        if (
            not isinstance(source_terms, list)
            or not isinstance(variants, list)
            or not isinstance(target, str)
            or not target
            or not isinstance(rule_id, str)
            or not rule_id
        ):
            raise LibraryScopeError("invalid LIBRARY source-surface replacement")
        if not any(
            isinstance(term, str)
            and term
            and compact_source_surface(term) in compact_source
            for term in source_terms
        ):
            continue
        replacements.extend(
            (variant, target, rule_id)
            for variant in variants
            if isinstance(variant, str) and variant
        )
    for variant, target, rule_id in sorted(
        set(replacements),
        key=lambda item: (-len(item[0]), item[0], item[2]),
    ):
        parts = candidate.split(target) if variant in target else [candidate]
        replaced = target.join(part.replace(variant, target) for part in parts)
        if replaced == candidate:
            continue
        candidate = replaced
        applied.append(f"{variant}→{target}[{rule_id}:source-surface]")
    return candidate, applied


def apply_library_rules(
    text: str,
    config: Mapping[str, object],
    glossary_terms: Iterable[Mapping[str, object]] = (),
) -> tuple[str, list[str]]:
    """Apply deterministic glossary, literal, and punctuation review rules."""

    candidate, applied = apply_glossary_variants(text, glossary_terms)
    literal_rules = config.get("literal_replacements")
    if not isinstance(literal_rules, list):
        raise LibraryScopeError("literal_replacements must be an array")
    for rule in literal_rules:
        if not isinstance(rule, Mapping):
            raise LibraryScopeError("invalid LIBRARY literal replacement")
        before = rule.get("from")
        after = rule.get("to")
        if not isinstance(before, str) or not isinstance(after, str):
            raise LibraryScopeError("invalid LIBRARY literal replacement")
        if before in candidate:
            candidate = candidate.replace(before, after)
            applied.append(f"{before}→{after}")

    style = config.get("style_rules")
    if not isinstance(style, Mapping):
        raise LibraryScopeError("style_rules must be an object")
    if style.get("normalize_curly_single_quote_pairs"):
        normalized = re.sub(r"‘([^’\n]+)’", r"“\1”", candidate)
        if normalized != candidate:
            candidate = normalized
            applied.append("中文单引号→中文双引号")
    if style.get("normalize_ascii_quote_pairs"):
        normalized = re.sub(r'"([^"\n]+)"', r"“\1”", candidate)
        if normalized != candidate:
            candidate = normalized
            applied.append("ASCII双引号→中文双引号")
    if style.get("normalize_plant_token"):
        normalized = re.sub(
            r"(?<![A-Za-z])plant(?![A-Za-z])",
            "PLANT",
            candidate,
            flags=re.I,
        )
        if normalized != candidate:
            candidate = normalized
            applied.append("PLANT大小写")
    return candidate, applied


def apply_source_bound_review_replacements(
    text: str,
    config: Mapping[str, object],
    relevant_term_ids: set[str],
) -> tuple[str, list[str]]:
    """Apply reviewed variants only when the matching glossary ID is bound."""

    candidate = text
    applied: list[str] = []
    replacements: list[tuple[str, str, str]] = []
    rules = config.get("source_bound_replacements", [])
    if not isinstance(rules, list):
        raise LibraryScopeError("source_bound_replacements must be an array")
    for rule in rules:
        if not isinstance(rule, Mapping):
            raise LibraryScopeError("invalid LIBRARY source-bound replacement")
        term_id = rule.get("glossary_id")
        target = rule.get("to")
        variants = rule.get("from", [])
        if (
            term_id not in relevant_term_ids
            or not isinstance(target, str)
            or not target
            or not isinstance(variants, list)
        ):
            continue
        replacements.extend(
            (variant, target, str(term_id))
            for variant in variants
            if isinstance(variant, str) and variant
        )
    for variant, target, term_id in sorted(
        set(replacements),
        key=lambda item: (-len(item[0]), item[0], item[2]),
    ):
        parts = candidate.split(target) if variant in target else [candidate]
        replaced = target.join(part.replace(variant, target) for part in parts)
        if replaced == candidate:
            continue
        candidate = replaced
        applied.append(f"{variant}→{target}[{term_id}:library-review]")
    return candidate, applied


ZKAN_TEXT_TAGS = frozenset(
    {
        "ACTR",
        "CHFN",
        "CHNN",
        "DSC2",
        "DSCR",
        "HEIT",
        "KANA",
        "PLTN",
        "PRDC",
        "RBTN",
        "SRCE",
        "WEIT",
        "WORD",
    }
)
ZKAN_BINARY_TAGS = frozenset({"LOOK", "LorR", "VOIC"})
ZKAN_KINDS = frozenset({"CHAR", "KYWD", "ROBO"})
ZKAN_ESCAPE_BYTE = 0x5E
ZKN_WRAPPER_SIZE = 0x20


REQUIRED_SURFACE_IDS = frozenset(
    {
        "library-menu",
        "robot-encyclopedia",
        "character-encyclopedia",
        "glossary",
        "sound-select",
        "scenario-chart",
        "strategy-qa",
    }
)


def _number(value: object, label: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError as exc:
            raise LibraryScopeError(f"{label} is not an integer") from exc
    raise LibraryScopeError(f"{label} must be an integer")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def zkan_escape_transform(data: bytes) -> bytes:
    """Apply the involutory ZKAN byte transform used by the retail game.

    NUL and ``0x5e`` are escape values and remain unchanged.  Every other
    byte is XORed with ``0x5e``.  The same operation decodes retail data and
    re-encodes a rebuilt ZKAN payload.
    """

    return bytes(
        value
        if value in (0, ZKAN_ESCAPE_BYTE)
        else value ^ ZKAN_ESCAPE_BYTE
        for value in bytes(data)
    )


@dataclass(frozen=True)
class ZkanField:
    tag: str
    data: bytes
    text: str | None


@dataclass(frozen=True)
class ZkanDocument:
    kind: str
    version: int
    fields: tuple[ZkanField, ...]
    decoded_payload_size: int
    decoded_payload_sha256: str

    def field(self, tag: str) -> ZkanField:
        matches = [field for field in self.fields if field.tag == tag]
        if len(matches) != 1:
            raise LibraryScopeError(
                f"ZKAN field {tag!r} occurs {len(matches)} times"
            )
        return matches[0]


def _unpack_u32(data: bytes, offset: int, label: str) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise LibraryScopeError(f"{label} exceeds its buffer")
    return struct.unpack_from("<I", data, offset)[0]


def _ascii_tag(data: bytes, offset: int, label: str) -> str:
    if offset < 0 or offset + 4 > len(data):
        raise LibraryScopeError(f"{label} exceeds its buffer")
    try:
        return data[offset : offset + 4].decode("ascii")
    except UnicodeDecodeError as exc:
        raise LibraryScopeError(f"{label} is not ASCII") from exc


def parse_zkn_decoded_chunk(decoded_chunk: bytes) -> ZkanDocument:
    """Parse one native-decoded MTVZKN chunk into its ZKAN fields.

    ``srwz.codec.decode`` returns a 0x20-byte wrapper followed by an escaped
    ZKAN document.  This parser validates every declared boundary before it
    decodes Shift-JIS text; malformed or unknown tags fail closed.
    """

    source = bytes(decoded_chunk)
    if len(source) < ZKN_WRAPPER_SIZE:
        raise LibraryScopeError("decoded ZKN chunk is shorter than its wrapper")
    wrapper_values = struct.unpack_from("<8I", source, 0)
    item_count, payload_offset, reserved, payload_size, payload_size_copy = (
        wrapper_values[:5]
    )
    if item_count != 1:
        raise LibraryScopeError(
            f"decoded ZKN wrapper item count is {item_count}, expected 1"
        )
    if payload_offset != ZKN_WRAPPER_SIZE:
        raise LibraryScopeError(
            "decoded ZKN wrapper payload offset is "
            f"0x{payload_offset:X}, expected 0x{ZKN_WRAPPER_SIZE:X}"
        )
    if reserved != 0:
        raise LibraryScopeError("decoded ZKN wrapper reserved word is nonzero")
    if payload_size != payload_size_copy:
        raise LibraryScopeError("decoded ZKN wrapper payload sizes disagree")
    if payload_offset + payload_size != len(source):
        raise LibraryScopeError(
            "decoded ZKN wrapper does not cover the complete decoded chunk"
        )
    if any(wrapper_values[5:]):
        raise LibraryScopeError("decoded ZKN wrapper padding is nonzero")

    escaped_payload = source[payload_offset : payload_offset + payload_size]
    payload = zkan_escape_transform(escaped_payload)
    if len(payload) < 0x20:
        raise LibraryScopeError("ZKAN payload is shorter than its header")
    if payload[:4] != b"ZKAN":
        raise LibraryScopeError("ZKAN payload magic is missing")
    kind = _ascii_tag(payload, 4, "ZKAN kind")
    if kind not in ZKAN_KINDS:
        raise LibraryScopeError(f"unsupported ZKAN kind: {kind!r}")
    version = _unpack_u32(payload, 8, "ZKAN version")
    if version != 0x100:
        raise LibraryScopeError(
            f"unsupported ZKAN version: 0x{version:X}"
        )
    header_size = _unpack_u32(payload, 12, "ZKAN header size")
    if header_size != 0x0C:
        raise LibraryScopeError(
            f"unsupported ZKAN header size: 0x{header_size:X}"
        )
    if payload[16:20] != b"DSIZ" or payload[24:28] != b"DATA":
        raise LibraryScopeError("ZKAN DSIZ/DATA header is malformed")
    document_size = _unpack_u32(payload, 20, "ZKAN DSIZ")
    data_size = _unpack_u32(payload, 28, "ZKAN DATA size")
    if document_size != data_size + 8:
        raise LibraryScopeError("ZKAN DSIZ does not cover its DATA record")
    document_end = data_size + 0x20
    if document_end > len(payload):
        raise LibraryScopeError("ZKAN DATA size exceeds the payload")
    if any(payload[document_end:]):
        raise LibraryScopeError("ZKAN payload has nonzero alignment padding")
    payload = payload[:document_end]

    fields: list[ZkanField] = []
    seen_tags: set[str] = set()
    cursor = 0x20
    while cursor < len(payload):
        tag = _ascii_tag(payload, cursor, "ZKAN field tag")
        size = _unpack_u32(payload, cursor + 4, f"ZKAN {tag} size")
        field_start = cursor + 8
        field_end = field_start + size
        if field_end > len(payload):
            raise LibraryScopeError(f"ZKAN {tag} field exceeds DATA")
        if tag in seen_tags:
            raise LibraryScopeError(f"duplicate ZKAN field tag: {tag}")
        seen_tags.add(tag)
        raw = payload[field_start:field_end]
        if tag in ZKAN_TEXT_TAGS:
            try:
                text = raw.decode("cp932")
            except UnicodeDecodeError as exc:
                raise LibraryScopeError(
                    f"ZKAN {tag} field is not valid Shift-JIS"
                ) from exc
        elif tag in ZKAN_BINARY_TAGS:
            text = None
        else:
            raise LibraryScopeError(f"unsupported ZKAN field tag: {tag!r}")
        fields.append(ZkanField(tag=tag, data=raw, text=text))
        cursor = field_end
    if cursor != len(payload):
        raise LibraryScopeError("ZKAN DATA fields do not end at its boundary")

    expected_by_kind: Mapping[str, Sequence[str]] = {
        "ROBO": (
            "PRDC",
            "LorR",
            "RBTN",
            "PLTN",
            "HEIT",
            "WEIT",
            "DSCR",
            "DSC2",
        ),
        "CHAR": (
            "CHFN",
            "CHNN",
            "PRDC",
            "ACTR",
            "LOOK",
            "DSCR",
            "DSC2",
        ),
        "KYWD": ("WORD", "SRCE", "DSCR", "DSC2"),
    }
    tags = tuple(field.tag for field in fields)
    required = expected_by_kind[kind]
    if any(tag not in tags for tag in required):
        missing = [tag for tag in required if tag not in tags]
        raise LibraryScopeError(
            f"ZKAN {kind} document is missing required fields: {missing}"
        )
    allowed = set(required)
    if kind == "ROBO":
        allowed.add("KANA")
    if kind == "CHAR":
        allowed.add("VOIC")
    if any(tag not in allowed for tag in tags):
        extras = [tag for tag in tags if tag not in allowed]
        raise LibraryScopeError(
            f"ZKAN {kind} document has unexpected fields: {extras}"
        )
    return ZkanDocument(
        kind=kind,
        version=version,
        fields=tuple(fields),
        decoded_payload_size=len(payload),
        decoded_payload_sha256=_sha256(payload),
    )


def parse_runtime_zkn_decoded_chunk(
    decoded_chunk: bytes,
    table: TextTable,
) -> ZkanDocument:
    """Parse a localized ZKAN chunk through the active runtime codebook.

    Retail ZKAN strings are ordinary CP932, while localized strings reuse the
    game's two-byte text codes and the flattened Chinese font.  Structural
    validation remains identical to :func:`parse_zkn_decoded_chunk`; only the
    text-field decoding step differs.
    """

    source = bytes(decoded_chunk)
    if len(source) < ZKN_WRAPPER_SIZE:
        raise LibraryScopeError("decoded ZKN chunk is shorter than its wrapper")
    wrapper_values = struct.unpack_from("<8I", source, 0)
    item_count, payload_offset, reserved, payload_size, payload_size_copy = (
        wrapper_values[:5]
    )
    if item_count != 1 or payload_offset != ZKN_WRAPPER_SIZE or reserved != 0:
        raise LibraryScopeError("localized ZKN wrapper header is malformed")
    if payload_size != payload_size_copy:
        raise LibraryScopeError("localized ZKN wrapper payload sizes disagree")
    if payload_offset + payload_size != len(source) or any(wrapper_values[5:]):
        raise LibraryScopeError("localized ZKN wrapper boundary is malformed")

    escaped_payload = source[payload_offset : payload_offset + payload_size]
    payload = zkan_escape_transform(escaped_payload)
    if len(payload) < 0x20 or payload[:4] != b"ZKAN":
        raise LibraryScopeError("localized ZKAN payload header is missing")
    kind = _ascii_tag(payload, 4, "localized ZKAN kind")
    version = _unpack_u32(payload, 8, "localized ZKAN version")
    header_size = _unpack_u32(payload, 12, "localized ZKAN header size")
    if kind not in ZKAN_KINDS or version != 0x100 or header_size != 0x0C:
        raise LibraryScopeError("localized ZKAN identity is unsupported")
    if payload[16:20] != b"DSIZ" or payload[24:28] != b"DATA":
        raise LibraryScopeError("localized ZKAN DSIZ/DATA header is malformed")
    document_size = _unpack_u32(payload, 20, "localized ZKAN DSIZ")
    data_size = _unpack_u32(payload, 28, "localized ZKAN DATA size")
    if document_size != data_size + 8:
        raise LibraryScopeError("localized ZKAN DSIZ does not cover DATA")
    document_end = data_size + 0x20
    if document_end > len(payload) or any(payload[document_end:]):
        raise LibraryScopeError("localized ZKAN payload padding is malformed")
    payload = payload[:document_end]

    fields: list[ZkanField] = []
    seen_tags: set[str] = set()
    cursor = 0x20
    while cursor < len(payload):
        tag = _ascii_tag(payload, cursor, "localized ZKAN field tag")
        size = _unpack_u32(payload, cursor + 4, f"localized ZKAN {tag} size")
        field_start = cursor + 8
        field_end = field_start + size
        if field_end > len(payload) or tag in seen_tags:
            raise LibraryScopeError(f"localized ZKAN {tag} field is malformed")
        seen_tags.add(tag)
        raw = payload[field_start:field_end]
        if tag in ZKAN_TEXT_TAGS:
            try:
                decoded = decode_text(
                    raw,
                    0,
                    table,
                    end=len(raw),
                    allow_end=True,
                )
            except ValueError as exc:
                raise LibraryScopeError(
                    f"localized ZKAN {tag} field cannot be decoded"
                ) from exc
            if decoded.unknown_code_count or decoded.end != len(raw):
                raise LibraryScopeError(
                    f"localized ZKAN {tag} field has unknown or trailing codes"
                )
            text = decoded.text
        elif tag in ZKAN_BINARY_TAGS:
            text = None
        else:
            raise LibraryScopeError(f"unsupported localized ZKAN tag: {tag!r}")
        fields.append(ZkanField(tag=tag, data=raw, text=text))
        cursor = field_end

    # Reuse the retail parser's exact per-kind field contract without asking
    # it to interpret localized text bytes as CP932.
    expected_by_kind: Mapping[str, Sequence[str]] = {
        "ROBO": ("PRDC", "LorR", "RBTN", "PLTN", "HEIT", "WEIT", "DSCR", "DSC2"),
        "CHAR": ("CHFN", "CHNN", "PRDC", "ACTR", "LOOK", "DSCR", "DSC2"),
        "KYWD": ("WORD", "SRCE", "DSCR", "DSC2"),
    }
    required = expected_by_kind[kind]
    tags = tuple(field.tag for field in fields)
    allowed = set(required)
    if kind == "ROBO":
        allowed.add("KANA")
    if kind == "CHAR":
        allowed.add("VOIC")
    if any(tag not in tags for tag in required) or any(
        tag not in allowed for tag in tags
    ):
        raise LibraryScopeError("localized ZKAN field contract drifted")
    return ZkanDocument(
        kind=kind,
        version=version,
        fields=tuple(fields),
        decoded_payload_size=len(payload),
        decoded_payload_sha256=_sha256(payload),
    )


def build_runtime_zkn_decoded_chunk(
    document: ZkanDocument,
    table: TextTable,
    replacements: Mapping[str, str],
    *,
    overrides: Mapping[str, int] | None = None,
    alignment: int = 16,
) -> bytes:
    """Serialize one localized ZKAN document with preserved binary fields."""

    if alignment <= 0 or alignment & (alignment - 1):
        raise LibraryScopeError("ZKAN decoded alignment must be a power of two")
    known_tags = {field.tag for field in document.fields if field.text is not None}
    if set(replacements) != known_tags:
        missing = sorted(known_tags - set(replacements))
        extra = sorted(set(replacements) - known_tags)
        raise LibraryScopeError(
            f"localized ZKAN replacement coverage drift: missing={missing}, extra={extra}"
        )

    records = bytearray()
    for field in document.fields:
        try:
            tag = field.tag.encode("ascii")
        except UnicodeEncodeError as exc:  # pragma: no cover - parsed tags are ASCII
            raise LibraryScopeError("ZKAN field tag is not ASCII") from exc
        if len(tag) != 4:
            raise LibraryScopeError("ZKAN field tag must be four bytes")
        if field.text is None:
            data = field.data
        else:
            data = encode_text(
                replacements[field.tag],
                table,
                overrides=overrides,
                terminate=False,
            )
        records.extend(tag)
        records.extend(struct.pack("<I", len(data)))
        records.extend(data)

    data_size = len(records)
    payload = bytearray()
    payload.extend(b"ZKAN")
    payload.extend(document.kind.encode("ascii"))
    payload.extend(struct.pack("<II", document.version, 0x0C))
    payload.extend(b"DSIZ")
    payload.extend(struct.pack("<I", data_size + 8))
    payload.extend(b"DATA")
    payload.extend(struct.pack("<I", data_size))
    payload.extend(records)
    padded_payload_size = (len(payload) + alignment - 1) & -alignment
    payload.extend(bytes(padded_payload_size - len(payload)))

    wrapper = struct.pack(
        "<8I",
        1,
        ZKN_WRAPPER_SIZE,
        0,
        len(payload),
        len(payload),
        0,
        0,
        0,
    )
    return wrapper + zkan_escape_transform(payload)


def _require_sha256(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise LibraryScopeError(
            f"{label} must be 64 lowercase hexadecimal digits"
        )
    return value


def validate_library_scope_mapping(raw: Mapping[str, object]) -> None:
    """Validate the decisions that must not drift during v0.2 development."""

    if not isinstance(raw, Mapping):
        raise LibraryScopeError("LIBRARY config root must be an object")
    if raw.get("schema_version") != 1:
        raise LibraryScopeError("unsupported LIBRARY config schema")
    if raw.get("release") != "0.2.0":
        raise LibraryScopeError("LIBRARY scope must target release 0.2.0")
    if raw.get("decision") != "include_complete_library":
        raise LibraryScopeError("v0.2 must include the complete LIBRARY scope")

    surfaces = raw.get("surfaces")
    if not isinstance(surfaces, list):
        raise LibraryScopeError("LIBRARY surfaces must be a list")
    surface_ids = []
    for surface in surfaces:
        if not isinstance(surface, Mapping):
            raise LibraryScopeError("LIBRARY surface must be an object")
        surface_id = surface.get("id")
        if not isinstance(surface_id, str) or not surface_id:
            raise LibraryScopeError("LIBRARY surface id must be non-empty")
        surface_ids.append(surface_id)
    if len(surface_ids) != len(set(surface_ids)):
        raise LibraryScopeError("LIBRARY surface ids contain duplicates")
    if set(surface_ids) != REQUIRED_SURFACE_IDS:
        missing = sorted(REQUIRED_SURFACE_IDS - set(surface_ids))
        extra = sorted(set(surface_ids) - REQUIRED_SURFACE_IDS)
        raise LibraryScopeError(
            f"LIBRARY surfaces are incomplete: missing={missing}, extra={extra}"
        )

    sound = raw.get("sound_select")
    if not isinstance(sound, Mapping):
        raise LibraryScopeError("sound_select config must be an object")
    if sound.get("track_title_policy") != (
        "preserve_original_japanese_byte_exact"
    ):
        raise LibraryScopeError("sound track titles must remain byte-exact")
    if sound.get("track_titles_in_translation_corpus") is not False:
        raise LibraryScopeError("sound track titles cannot enter translation corpus")


@dataclass(frozen=True)
class SoundTitleSpanLock:
    start: int
    end: int
    alignment: int
    expected_title_count: int
    expected_span_sha256: str

    @classmethod
    def from_mapping(
        cls, raw: Mapping[str, object]
    ) -> "SoundTitleSpanLock":
        if not isinstance(raw, Mapping):
            raise LibraryScopeError("sound title span lock must be an object")
        lock = cls(
            start=_number(raw.get("start"), "sound title span start"),
            end=_number(raw.get("end"), "sound title span end"),
            alignment=_number(
                raw.get("alignment"), "sound title span alignment"
            ),
            expected_title_count=_number(
                raw.get("expected_title_count"),
                "sound title expected count",
            ),
            expected_span_sha256=_require_sha256(
                raw.get("expected_span_sha256"),
                "sound title span SHA-256",
            ),
        )
        if not 0 <= lock.start < lock.end:
            raise LibraryScopeError("sound title span is empty or reversed")
        if lock.alignment <= 0 or lock.start % lock.alignment:
            raise LibraryScopeError("sound title span alignment is invalid")
        if lock.expected_title_count <= 0:
            raise LibraryScopeError("sound title count must be positive")
        return lock


@dataclass(frozen=True)
class SoundTrackTitle:
    ordinal: int
    start: int
    end: int
    text: str


def parse_sound_track_titles(
    decoded_compdata: bytes,
    table: TextTable,
    lock: SoundTitleSpanLock,
) -> tuple[SoundTrackTitle, ...]:
    """Parse the aligned, NUL-terminated stock title strings in one span."""

    source = bytes(decoded_compdata)
    if lock.end > len(source):
        raise LibraryScopeError(
            "sound title span exceeds decoded COMPDATA"
        )

    entries: list[SoundTrackTitle] = []
    for offset in range(lock.start, lock.end, lock.alignment):
        if source[offset] == 0:
            continue
        if offset != lock.start and source[offset - 2 : offset] != b"\0\0":
            continue
        try:
            decoded = decode_text(source, offset, table, end=lock.end)
        except ValueError:
            continue
        if decoded.unknown_code_count or not decoded.text:
            continue
        if decoded.end > lock.end:
            raise LibraryScopeError(
                f"sound title at 0x{offset:X} exceeds its locked span"
            )
        entries.append(
            SoundTrackTitle(
                ordinal=len(entries),
                start=offset,
                end=decoded.end,
                text=decoded.text,
            )
        )

    if len(entries) != lock.expected_title_count:
        raise LibraryScopeError(
            "sound title count mismatch: "
            f"expected {lock.expected_title_count}, got {len(entries)}"
        )
    return tuple(entries)


def verify_sound_title_source(
    decoded_compdata: bytes,
    table: TextTable,
    lock: SoundTitleSpanLock,
) -> tuple[SoundTrackTitle, ...]:
    """Verify the stock decoded span hash and its 85 parseable titles."""

    source = bytes(decoded_compdata)
    if lock.end > len(source):
        raise LibraryScopeError(
            "sound title span exceeds decoded COMPDATA"
        )
    actual_hash = _sha256(source[lock.start : lock.end])
    if actual_hash != lock.expected_span_sha256:
        raise LibraryScopeError(
            "sound title source span SHA-256 mismatch: "
            f"expected {lock.expected_span_sha256}, got {actual_hash}"
        )
    return parse_sound_track_titles(source, table, lock)


def verify_sound_titles_preserved(
    source_decoded_compdata: bytes,
    candidate_decoded_compdata: bytes,
    lock: SoundTitleSpanLock,
) -> None:
    """Require exact decoded title bytes in a rebuilt COMPDATA candidate."""

    source = bytes(source_decoded_compdata)
    candidate = bytes(candidate_decoded_compdata)
    if lock.end > len(source) or lock.end > len(candidate):
        raise LibraryScopeError(
            "sound title span exceeds source or candidate COMPDATA"
        )
    source_span = source[lock.start : lock.end]
    candidate_span = candidate[lock.start : lock.end]
    if candidate_span != source_span:
        first_difference = next(
            index
            for index, (before, after) in enumerate(
                zip(source_span, candidate_span)
            )
            if before != after
        )
        raise LibraryScopeError(
            "sound titles changed in candidate at decoded COMPDATA offset "
            f"0x{lock.start + first_difference:X}"
        )


def verify_jtim_library_menu_record(
    jtim_data: bytes,
    raw_lock: Mapping[str, object],
) -> dict[str, int | str]:
    """Verify the fixed JTIM TIM2 record that owns the six LIBRARY labels."""

    if not isinstance(raw_lock, Mapping):
        raise LibraryScopeError("JTIM LIBRARY menu lock must be an object")
    record_index = _number(raw_lock.get("record_index"), "JTIM record index")
    expected_offset = _number(raw_lock.get("offset"), "JTIM record offset")
    expected_size = _number(raw_lock.get("size"), "JTIM record size")
    expected_hash = _require_sha256(
        raw_lock.get("sha256"), "JTIM record SHA-256"
    )
    expected_width = _number(raw_lock.get("width"), "JTIM record width")
    expected_height = _number(raw_lock.get("height"), "JTIM record height")
    expected_image_type = _number(
        raw_lock.get("image_type"), "JTIM record image type"
    )
    expected_clut_colors = _number(
        raw_lock.get("clut_color_count"), "JTIM record CLUT color count"
    )

    records = scan_tim2(jtim_data)
    if not 0 <= record_index < len(records):
        raise LibraryScopeError(
            f"JTIM record index {record_index} is outside the TIM2 scan"
        )
    record = records[record_index]
    if len(record.pictures) != 1:
        raise LibraryScopeError("JTIM LIBRARY menu must have one TIM2 picture")
    picture = record.pictures[0]
    actual = {
        "offset": record.offset,
        "size": record.size,
        "width": picture.width,
        "height": picture.height,
        "image_type": picture.image_type,
        "clut_color_count": picture.clut_color_count,
    }
    expected = {
        "offset": expected_offset,
        "size": expected_size,
        "width": expected_width,
        "height": expected_height,
        "image_type": expected_image_type,
        "clut_color_count": expected_clut_colors,
    }
    if actual != expected:
        raise LibraryScopeError(
            f"JTIM LIBRARY menu metadata mismatch: {actual}, expected {expected}"
        )
    stored = bytes(jtim_data[record.offset : record.offset + record.size])
    actual_hash = _sha256(stored)
    if actual_hash != expected_hash:
        raise LibraryScopeError(
            "JTIM LIBRARY menu record SHA-256 mismatch: "
            f"expected {expected_hash}, got {actual_hash}"
        )
    return {**actual, "sha256": actual_hash}


__all__ = [
    "LibraryScopeError",
    "SoundTitleSpanLock",
    "SoundTrackTitle",
    "ZkanDocument",
    "ZkanField",
    "build_runtime_zkn_decoded_chunk",
    "parse_zkn_decoded_chunk",
    "parse_runtime_zkn_decoded_chunk",
    "parse_sound_track_titles",
    "verify_jtim_library_menu_record",
    "verify_sound_title_source",
    "verify_sound_titles_preserved",
    "validate_library_scope_mapping",
    "zkan_escape_transform",
]
