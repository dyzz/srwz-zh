#!/usr/bin/env python3
"""Export stable SRWZ corpus JSONL under ignored work/."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from srwz.corpus import (
    CorpusError,
    canonical_json_line,
    corpus_digest,
    export_corpus,
)
from srwz.diagnostics import require_work_output
from srwz.text import decode_text, encode_text, load_text_table


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--parse-report",
        type=Path,
        default=WORK_ROOT / "parsed" / "srwz-data.json",
    )
    parser.add_argument(
        "--jsonl-output",
        type=Path,
        default=WORK_ROOT / "corpus" / "srwz-corpus.jsonl",
    )
    parser.add_argument(
        "--metadata-output",
        type=Path,
        default=WORK_ROOT / "corpus" / "corpus-export.json",
    )
    parser.add_argument(
        "--text-table",
        type=Path,
        default=(
            PROJECT_ROOT
            / "vendor"
            / "upstream-python"
            / "project"
            / "tbl_all.json"
        ),
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    jsonl_output = require_work_output(args.jsonl_output, WORK_ROOT)
    metadata_output = require_work_output(args.metadata_output, WORK_ROOT)
    for output in (jsonl_output, metadata_output):
        if output.exists() and not args.force:
            raise SystemExit(f"output exists; use --force: {output}")

    report = json.loads(args.parse_report.read_text(encoding="utf-8"))
    entries = export_corpus(report)
    table = load_text_table(args.text_table)
    text_round_trip_exact_count = 0
    for entry in entries:
        encoded = encode_text(entry.source_text, table, terminate=True)
        decoded = decode_text(encoded, 0, table)
        if decoded.text != entry.source_text:
            raise CorpusError(
                f"text serialization round-trip mismatch for {entry.entry_id}"
            )
        text_round_trip_exact_count += 1

    jsonl_output.parent.mkdir(parents=True, exist_ok=True)
    with jsonl_output.open("w", encoding="utf-8", newline="\n") as output:
        for entry in entries:
            output.write(canonical_json_line(entry))
            output.write("\n")

    domains = Counter(entry.domain for entry in entries)
    kinds = Counter(entry.kind for entry in entries)
    metadata = {
        "schema_version": 1,
        "content_policy": (
            "The JSONL contains extracted Japanese text and remains under "
            "ignored work/. Only this aggregate metadata is publishable."
        ),
        "source_parse_report": str(args.parse_report.resolve()),
        "entry_count": len(entries),
        "text_round_trip_exact_count": text_round_trip_exact_count,
        "domain_counts": dict(sorted(domains.items())),
        "kind_counts": dict(sorted(kinds.items())),
        "aggregate_sha256": corpus_digest(entries),
    }
    metadata_output.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"corpus: entries={len(entries)} "
        f"menu={domains['menu']} story={domains['story']} "
        f"summary={domains['summary']} "
        f"text_round_trip={text_round_trip_exact_count}/{len(entries)}"
    )
    print(f"jsonl: {jsonl_output}")
    print(f"metadata: {metadata_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
