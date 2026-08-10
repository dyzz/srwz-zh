#!/usr/bin/env python3
"""Extract the retail LIBRARY ZKAN text into ignored review artifacts.

The command binds every text field to its compressed archive chunk and emits
one deduplicated model queue.  Japanese source text stays below ``work/`` and
is never written into the distributable corpus tree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from srwz.codec import decode
    from srwz.diagnostics import require_work_output
    from srwz.iso_layout import (
        ExecutableOffsetSpec,
        read_executable_archive_offsets,
    )
    from srwz.glossary import (
        GlossaryError,
        load_global_glossary,
        relevant_glossary_terms,
    )
    from srwz.library import (
        LibraryScopeError,
        parse_zkn_decoded_chunk,
        validate_library_scope_mapping,
    )
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from tools.srwz.codec import decode
    from tools.srwz.diagnostics import require_work_output
    from tools.srwz.iso_layout import (
        ExecutableOffsetSpec,
        read_executable_archive_offsets,
    )
    from tools.srwz.glossary import (
        GlossaryError,
        load_global_glossary,
        relevant_glossary_terms,
    )
    from tools.srwz.library import (
        LibraryScopeError,
        parse_zkn_decoded_chunk,
        validate_library_scope_mapping,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = PROJECT_ROOT / "config/library/v0.2.0.json"
DEFAULT_OUTPUT = WORK_ROOT / "corpus/library-v0.2/source"
DEFAULT_QUEUE = WORK_ROOT / "review/aliyun/library-v0.2/source-queue.jsonl"
DEFAULT_REPORT = WORK_ROOT / "review/aliyun/library-v0.2/extraction.json"

ARCHIVES = (
    ("robot", "DATA/MTVZKNRT.BIN", "ROBO"),
    ("character", "DATA/MTVZKNPT.BIN", "CHAR"),
    ("glossary", "DATA/MTVZKNKW.BIN", "KYWD"),
)
CONTEXT_SENSITIVE_HARD_TERM_PREFIXES = ("spirit/",)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def project_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def work_output(path: Path) -> Path:
    return require_work_output(project_path(path), WORK_ROOT).resolve()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise LibraryScopeError(f"JSON root is not an object: {path}")
    return value


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_jsonl(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(
                json.dumps(row, ensure_ascii=False, separators=(",", ":"))
                + "\n"
            )
    temporary.replace(path)


def verify_member(path: Path, lock: Mapping[str, object], member: str) -> bytes:
    if not path.is_file():
        raise LibraryScopeError(f"missing source member: {path}")
    data = path.read_bytes()
    expected_size = int(lock["size"])
    expected_hash = str(lock["sha256"])
    if len(data) != expected_size:
        raise LibraryScopeError(
            f"{member} size mismatch: expected {expected_size}, got {len(data)}"
        )
    actual_hash = sha256_bytes(data)
    if actual_hash != expected_hash:
        raise LibraryScopeError(
            f"{member} SHA-256 mismatch: expected {expected_hash}, got {actual_hash}"
        )
    return data


def load_glossary_terms() -> list[dict[str, object]]:
    try:
        return load_global_glossary(PROJECT_ROOT / "corpus/glossary")
    except GlossaryError as exc:
        raise LibraryScopeError(str(exc)) from exc


def relevant_terms(
    text: str, terms: Sequence[Mapping[str, object]]
) -> list[dict[str, object]]:
    try:
        return relevant_glossary_terms(
            text,
            terms,
            context_sensitive_hard_prefixes=(
                CONTEXT_SENSITIVE_HARD_TERM_PREFIXES
            ),
        )
    except GlossaryError as exc:
        raise LibraryScopeError(str(exc)) from exc


def model_source_text(text: str) -> str:
    """Remove retail hard wrapping while retaining paragraph indentation."""

    return text.replace("\r", "").replace("\n", "")


def extract_archive(
    *,
    domain: str,
    member: str,
    expected_kind: str,
    archive: bytes,
    executable: bytes,
    lock: Mapping[str, object],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    spec = ExecutableOffsetSpec(
        name=member,
        member=member,
        table_start=int(str(lock["slps_table_start"]), 0),
        table_end=int(str(lock["slps_table_end"]), 0),
    )
    offsets = read_executable_archive_offsets(executable, spec, len(archive))
    expected_count = int(lock["expected_chunk_count"])
    if len(offsets) - 1 != expected_count:
        raise LibraryScopeError(
            f"{member} entry count mismatch: expected {expected_count}, "
            f"got {len(offsets) - 1}"
        )

    documents: list[dict[str, object]] = []
    text_references: list[dict[str, object]] = []
    for index, (start, end) in enumerate(zip(offsets, offsets[1:])):
        stored = archive[start:end]
        result = decode(stored)
        if any(stored[result.consumed :]):
            raise LibraryScopeError(
                f"{member} chunk {index} has nonzero trailing bytes"
            )
        document = parse_zkn_decoded_chunk(result.output)
        if document.kind != expected_kind:
            raise LibraryScopeError(
                f"{member} chunk {index} is {document.kind}, expected {expected_kind}"
            )
        fields: list[dict[str, object]] = []
        for field in document.fields:
            field_id = f"library/{domain}/{index:03d}/{field.tag.lower()}"
            record: dict[str, object] = {
                "id": field_id,
                "tag": field.tag,
                "source_bytes_sha256": sha256_bytes(field.data),
                "source_byte_count": len(field.data),
            }
            if field.text is None:
                record["kind"] = "binary"
            else:
                record.update(
                    {
                        "kind": "text",
                        "source_text": field.text,
                        "source_text_sha256": sha256_text(field.text),
                    }
                )
                if field.text.strip():
                    text_references.append(
                        {
                            "field_id": field_id,
                            "domain": domain,
                            "entry_index": index,
                            "tag": field.tag,
                            "source_text": field.text,
                            "source_text_sha256": sha256_text(field.text),
                            "source_bytes_sha256": sha256_bytes(field.data),
                            "source_byte_count": len(field.data),
                        }
                    )
            fields.append(record)
        documents.append(
            {
                "schema_version": 1,
                "id": f"library/{domain}/{index:03d}",
                "domain": domain,
                "entry_index": index,
                "source_member": member,
                "stored_start": start,
                "stored_end": end,
                "stored_size": len(stored),
                "stored_sha256": sha256_bytes(stored),
                "native_consumed_size": result.consumed,
                "decoded_size": len(result.output),
                "decoded_sha256": sha256_bytes(result.output),
                "zkan_kind": document.kind,
                "zkan_payload_size": document.decoded_payload_size,
                "zkan_payload_sha256": document.decoded_payload_sha256,
                "fields": fields,
            }
        )
    return documents, text_references


def build_queue(
    references: Sequence[Mapping[str, object]],
    glossary: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    by_hash: dict[str, dict[str, object]] = {}
    grouped_refs: dict[str, list[dict[str, object]]] = defaultdict(list)
    for reference in references:
        source_hash = str(reference["source_text_sha256"])
        source_text = str(reference["source_text"])
        prior = by_hash.get(source_hash)
        if prior is not None and prior["source_text"] != source_text:
            raise LibraryScopeError(f"source text SHA-256 collision: {source_hash}")
        by_hash[source_hash] = {
            "source_text": source_text,
            "source_bytes_sha256": reference["source_bytes_sha256"],
        }
        grouped_refs[source_hash].append(
            {
                "field_id": reference["field_id"],
                "domain": reference["domain"],
                "entry_index": reference["entry_index"],
                "tag": reference["tag"],
                "source_byte_count": reference["source_byte_count"],
                "source_bytes_sha256": reference["source_bytes_sha256"],
            }
        )

    rows: list[dict[str, object]] = []
    for source_hash in sorted(by_hash):
        source_text = str(by_hash[source_hash]["source_text"])
        rows.append(
            {
                "schema_version": 1,
                "id": f"library-text/{source_hash[:16]}",
                "source_text": source_text,
                "model_source_text": model_source_text(source_text),
                "source_text_sha256": source_hash,
                "references": sorted(
                    grouped_refs[source_hash], key=lambda item: str(item["field_id"])
                ),
                "glossary_terms": relevant_terms(source_text, glossary),
                "review_state": "untranslated",
            }
        )
    ids = [str(row["id"]) for row in rows]
    if len(ids) != len(set(ids)):
        raise LibraryScopeError("truncated source hashes produced duplicate queue IDs")
    return rows


def main() -> int:
    args = parse_args()
    config_path = project_path(args.config).resolve()
    config = read_json(config_path)
    validate_library_scope_mapping(config)
    locks = config.get("source_member_locks")
    if not isinstance(locks, Mapping):
        raise LibraryScopeError("source_member_locks must be an object")

    executable_lock = locks["SLPS_258.87"]
    assert isinstance(executable_lock, Mapping)
    executable = verify_member(
        project_path(Path(str(executable_lock["path"]))).resolve(),
        executable_lock,
        "SLPS_258.87",
    )

    output_dir = work_output(args.output_dir)
    queue_path = work_output(args.queue)
    report_path = work_output(args.report)
    targets = [
        output_dir / f"{domain}.jsonl" for domain, _, _ in ARCHIVES
    ] + [queue_path, report_path]
    if not args.force:
        existing = [path for path in targets if path.exists()]
        if existing:
            raise FileExistsError(f"refusing to replace existing file: {existing[0]}")

    all_references: list[dict[str, object]] = []
    archive_reports: dict[str, dict[str, object]] = {}
    for domain, member, expected_kind in ARCHIVES:
        raw_lock = locks[member]
        assert isinstance(raw_lock, Mapping)
        archive = verify_member(
            project_path(Path(str(raw_lock["path"]))).resolve(), raw_lock, member
        )
        documents, references = extract_archive(
            domain=domain,
            member=member,
            expected_kind=expected_kind,
            archive=archive,
            executable=executable,
            lock=raw_lock,
        )
        write_jsonl(output_dir / f"{domain}.jsonl", documents)
        all_references.extend(references)
        archive_reports[domain] = {
            "source_member": member,
            "source_member_sha256": raw_lock["sha256"],
            "entry_count": len(documents),
            "text_field_reference_count": len(references),
            "output": str((output_dir / f"{domain}.jsonl").relative_to(PROJECT_ROOT)),
        }

    glossary = load_glossary_terms()
    queue = build_queue(all_references, glossary)
    write_jsonl(queue_path, queue)
    report = {
        "schema_version": 1,
        "kind": "library_v0.2_source_extraction",
        "release": "0.2.0",
        "source_authority": "original_disc_only",
        "japanese_source_policy": "ignored_work_artifacts_only",
        "archives": archive_reports,
        "text_field_reference_count": len(all_references),
        "unique_model_source_count": len(queue),
        "glossary_inventory_count": len(glossary),
        "queue": str(queue_path.relative_to(PROJECT_ROOT)),
        "queue_sha256": sha256_bytes(queue_path.read_bytes()),
        "sound_track_titles": {
            "included_in_queue": False,
            "policy": "preserve_original_japanese_byte_exact",
        },
    }
    write_json(report_path, report)
    print(
        f"entries={sum(item['entry_count'] for item in archive_reports.values())} "
        f"text_refs={len(all_references)} unique={len(queue)}"
    )
    print(report_path.relative_to(PROJECT_ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
