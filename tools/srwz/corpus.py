"""Stable corpus records derived from the read-only SRWZ parse report."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Iterable, Iterator, Mapping, Optional


CORPUS_SCHEMA_VERSION = 1
VALID_STATUSES = (
    "todo",
    "draft",
    "reviewed",
    "final",
    "runtime_verified",
)
STATUS_RANK = {
    status: rank for rank, status in enumerate(VALID_STATUSES)
}


class CorpusError(ValueError):
    """A corpus record is malformed, duplicated, or stale."""


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CorpusEntry:
    entry_id: str
    domain: str
    kind: str
    source_member: str
    source_member_sha256: str
    scope_index: Optional[int]
    section: str
    ordinal: int
    source_text: str
    source_text_sha256: str
    provenance: Mapping[str, object]
    translation: str = ""
    status: str = "todo"
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.entry_id:
            raise CorpusError("corpus entry id must be non-empty")
        if self.domain not in ("menu", "story", "summary"):
            raise CorpusError(f"invalid corpus domain: {self.domain!r}")
        if not self.kind or not self.source_member or not self.section:
            raise CorpusError("corpus kind, source member and section are required")
        if len(self.source_member_sha256) != 64:
            raise CorpusError("source member SHA-256 is malformed")
        if self.scope_index is not None and self.scope_index < 0:
            raise CorpusError("scope index must be non-negative")
        if self.ordinal < 0:
            raise CorpusError("ordinal must be non-negative")
        if text_sha256(self.source_text) != self.source_text_sha256:
            raise CorpusError(f"source text hash mismatch for {self.entry_id}")
        if self.status not in VALID_STATUSES:
            raise CorpusError(
                f"invalid translation status {self.status!r} "
                f"for {self.entry_id}"
            )
        if self.status != "todo" and not self.translation:
            raise CorpusError(
                f"{self.entry_id} status {self.status!r} requires translation"
            )

    def to_mapping(self, *, include_source_text: bool = True) -> dict:
        result = {
            "schema_version": CORPUS_SCHEMA_VERSION,
            "id": self.entry_id,
            "domain": self.domain,
            "kind": self.kind,
            "source_member": self.source_member,
            "source_member_sha256": self.source_member_sha256,
            "scope_index": self.scope_index,
            "section": self.section,
            "ordinal": self.ordinal,
            "source_text_sha256": self.source_text_sha256,
            "provenance": dict(self.provenance),
            "translation": self.translation,
            "status": self.status,
            "notes": self.notes,
        }
        if include_source_text:
            result["source_text"] = self.source_text
        return result


def _source(report: Mapping[str, object], key: str) -> Mapping[str, object]:
    sources = report.get("sources")
    if not isinstance(sources, dict) or key not in sources:
        raise CorpusError(f"parse report is missing source {key}")
    source = sources[key]
    if not isinstance(source, dict):
        raise CorpusError(f"parse report source {key} is malformed")
    return source


def _entry(
    raw: Mapping[str, object],
    *,
    domain: str,
    kind: str,
    source_member: str,
    source_member_sha256: str,
    scope_index: Optional[int],
    provenance: Mapping[str, object],
    section: Optional[str] = None,
) -> CorpusEntry:
    source_text = raw.get("text")
    if not isinstance(source_text, str):
        raise CorpusError("parsed entry text must be a string")
    return CorpusEntry(
        entry_id=str(raw["id"]),
        domain=domain,
        kind=kind,
        source_member=source_member,
        source_member_sha256=source_member_sha256,
        scope_index=scope_index,
        section=str(raw["section"] if section is None else section),
        ordinal=int(raw["ordinal"]),
        source_text=source_text,
        source_text_sha256=text_sha256(source_text),
        provenance=provenance,
    )


def export_corpus(report: Mapping[str, object]) -> tuple:
    parsed = report.get("parsed")
    if not isinstance(parsed, dict):
        raise CorpusError("parse report has no parsed data")
    entries = []

    menu_sources = {
        "SLPS": ("SLPS_258.87", _source(report, "SLPS_258.87")),
        "Compdata": (
            "DATA/COMPDATA.BN",
            _source(report, "COMPDATA.BN"),
        ),
    }
    for menu_file in parsed.get("menu", ()):
        friendly_name = str(menu_file["friendly_name"])
        if friendly_name not in menu_sources:
            raise CorpusError(f"unknown menu source {friendly_name!r}")
        source_member, source = menu_sources[friendly_name]
        for raw in menu_file["entries"]:
            entries.append(
                _entry(
                    raw,
                    domain="menu",
                    kind="menu",
                    source_member=source_member,
                    source_member_sha256=str(source["sha256"]),
                    scope_index=None,
                    provenance={
                        "file": friendly_name,
                        "pointer_offsets": raw["pointer_offsets"],
                        "target_offsets": raw["target_offsets"],
                        "embedded_hi": raw["embedded_hi"],
                        "embedded_lo": raw["embedded_lo"],
                    },
                )
            )

    stage_source = _source(report, "STAGE.BIN")
    for stage in parsed.get("story", ()):
        stage_index = int(stage["stage_index"])
        for raw in stage["entries"]:
            entries.append(
                _entry(
                    raw,
                    domain="story",
                    kind=str(raw["kind"]),
                    source_member="DATA/STAGE.BIN",
                    source_member_sha256=str(stage_source["sha256"]),
                    scope_index=stage_index,
                    provenance={
                        "pointer_offset": raw["pointer_offset"],
                        "text_offset": raw["text_offset"],
                        "speaker_id": raw["speaker_id"],
                    },
                )
            )

    summary_source = _source(report, "MTV_PROS.BIN")
    for summary in parsed.get("summary", ()):
        chunk_index = int(summary["chunk_index"])
        for raw in summary["entries"]:
            entries.append(
                _entry(
                    raw,
                    domain="summary",
                    kind="summary",
                    source_member="DATA/MTV_PROS.BIN",
                    source_member_sha256=str(summary_source["sha256"]),
                    scope_index=chunk_index,
                    provenance={
                        "text_offset": raw["text_offset"],
                        "allocated_length": raw["allocated_length"],
                    },
                    section="Text",
                )
            )

    entries.sort(key=lambda item: item.entry_id)
    validate_corpus(entries)
    return tuple(entries)


def validate_corpus(entries: Iterable[CorpusEntry]) -> None:
    seen = set()
    for entry in entries:
        if entry.entry_id in seen:
            raise CorpusError(f"duplicate corpus id: {entry.entry_id}")
        seen.add(entry.entry_id)


def validate_status_transition(
    previous: str,
    current: str,
    *,
    runtime_evidence: bool = False,
) -> None:
    """Reject backwards workflow changes and unverified runtime claims."""

    if previous not in STATUS_RANK:
        raise CorpusError(f"invalid previous translation status: {previous!r}")
    if current not in STATUS_RANK:
        raise CorpusError(f"invalid current translation status: {current!r}")
    if STATUS_RANK[current] < STATUS_RANK[previous]:
        raise CorpusError(
            f"translation status cannot move backwards: "
            f"{previous!r} -> {current!r}"
        )
    if current == "runtime_verified" and not runtime_evidence:
        raise CorpusError(
            "runtime_verified status requires explicit runtime evidence"
        )


def canonical_json_line(entry: CorpusEntry) -> str:
    return json.dumps(
        entry.to_mapping(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def corpus_digest(entries: Iterable[CorpusEntry]) -> str:
    digest = hashlib.sha256()
    for entry in entries:
        digest.update(canonical_json_line(entry).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def load_json_lines(lines: Iterable[str]) -> Iterator[dict]:
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise CorpusError(
                f"invalid corpus JSON on line {line_number}: {error}"
            ) from error
        if not isinstance(value, dict):
            raise CorpusError(
                f"corpus line {line_number} must be a JSON object"
            )
        yield value


__all__ = [
    "CORPUS_SCHEMA_VERSION",
    "CorpusEntry",
    "CorpusError",
    "VALID_STATUSES",
    "canonical_json_line",
    "corpus_digest",
    "export_corpus",
    "load_json_lines",
    "text_sha256",
    "validate_corpus",
    "validate_status_transition",
]
