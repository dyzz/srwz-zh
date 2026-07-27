#!/usr/bin/env python3
"""Build a review-only SRWZ Gundam index from cached Biligame pages."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
from typing import Iterable, Mapping, Optional
import urllib.parse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_ROOT = (
    PROJECT_ROOT / "work/review/sources/biligame"
)
DEFAULT_REPORT = (
    PROJECT_ROOT / "work/review/biligame-srwz-gundam-index.json"
)
DEFAULT_TSV = (
    PROJECT_ROOT / "work/review/biligame-srwz-gundam-index.tsv"
)
TARGET_PEOPLE_PAGES = {
    "机动战士Z高达人物",
    "机动战士高达seed人物",
    "机动战士高达SEED人物",
    "机动战士高达SEED DESTINY人物",
    "机动新世纪高达X人物",
    "逆A高达人物",
}
UNIT_INDEX_TITLE = "全机体资料"
WIKI_PREFIX = "https://wiki.biligame.com/gundam/"
RESERVED_PREFIXES = (
    "分类:",
    "文件:",
    "模板:",
    "特殊:",
    "MediaWiki:",
)
TITLED_LINK_RE = re.compile(
    r'\[([^\]\n]+)\]\((https://wiki\.biligame\.com/gundam/'
    r'[^\n]*?)\s+"([^"\n]*)"\)'
)
PLAIN_LINK_RE = re.compile(
    r"\[([^\]\n]+)\]\((https://wiki\.biligame\.com/gundam/"
    r"[^\s\)]+)\)"
)


def page_source_url(text: str) -> str:
    first_line = text.splitlines()[0] if text else ""
    prefix = "Source URL: "
    return first_line[len(prefix):].strip() if first_line.startswith(prefix) else ""


def page_title(text: str, source_url: str) -> str:
    heading = re.search(r"^# ([^#\n].*)$", text, flags=re.MULTILINE)
    if heading:
        return heading.group(1).strip()
    if source_url.startswith(WIKI_PREFIX):
        return urllib.parse.unquote(source_url[len(WIKI_PREFIX):]).replace("_", " ")
    return ""


def _content_slice(text: str, start_heading: str) -> str:
    start = text.find(start_heading)
    if start == -1:
        return ""
    end = text.find("取自“", start)
    return text[start:] if end == -1 else text[start:end]


def _normalized_wiki_link(
    label: str,
    url: str,
    title: str,
) -> Optional[tuple[str, str]]:
    if "redlink=1" in url or "action=edit" in url or "/index.php?" in url:
        return None
    clean_url = url.split("#", 1)[0]
    decoded = urllib.parse.unquote(clean_url[len(WIKI_PREFIX):]).replace("_", " ")
    candidate = (title or label or decoded).strip()
    if not candidate or candidate.startswith(RESERVED_PREFIXES):
        return None
    return candidate, clean_url


def parse_wiki_links(text: str) -> tuple[dict[str, str], ...]:
    links: dict[str, str] = {}
    for match in TITLED_LINK_RE.finditer(text):
        normalized = _normalized_wiki_link(
            match.group(1),
            match.group(2),
            match.group(3),
        )
        if normalized:
            title, url = normalized
            links.setdefault(url, title)
    for match in PLAIN_LINK_RE.finditer(text):
        normalized = _normalized_wiki_link(
            match.group(1),
            match.group(2),
            "",
        )
        if normalized:
            title, url = normalized
            links.setdefault(url, title)
    return tuple(
        {"title": title, "url": url}
        for url, title in sorted(links.items(), key=lambda item: item[1])
    )


def extract_people_entries(
    title: str,
    source_url: str,
    text: str,
) -> tuple[dict[str, str], ...]:
    content = _content_slice(text, f"# {title}")
    entries = []
    for link in parse_wiki_links(content):
        if link["url"] == source_url:
            continue
        entries.append(
            {
                "category": "person",
                "series": title.removesuffix("人物"),
                "zh_title": link["title"],
                "url": link["url"],
            }
        )
    return tuple(entries)


def extract_unit_entries(text: str) -> tuple[dict[str, str], ...]:
    content = _content_slice(text, "## A-D开头型号")
    return tuple(
        {
            "category": "unit",
            "series": "",
            "zh_title": link["title"],
            "url": link["url"],
        }
        for link in parse_wiki_links(content)
    )


def extract_detail_facts(
    title: str,
    source_url: str,
    text: str,
) -> dict[str, object]:
    facts: dict[str, object] = {
        "title": title,
        "url": source_url,
    }
    for field, key in (
        ("中文名称", "zh_name"),
        ("日文名称", "jp_name"),
    ):
        match = re.search(
            rf"\| {field} \| ([^|\n]+)",
            text,
        )
        if match:
            facts[key] = match.group(1).strip()
    foreign = re.search(
        r"(?:\| )?外文(?: \|)?\s*([^|\n]+)",
        text,
    )
    if foreign:
        facts["foreign_name"] = foreign.group(1).strip()
    return facts


def build_reference(source_root: Path) -> dict[str, object]:
    pages = []
    people_by_url: dict[str, dict[str, object]] = {}
    units: dict[str, dict[str, str]] = {}
    details = []
    people_page_count = 0
    unit_index_count = 0

    for path in sorted(source_root.rglob("*.md")):
        data = path.read_bytes()
        text = data.decode("utf-8")
        source_url = page_source_url(text)
        title = page_title(text, source_url)
        if not source_url:
            continue
        pages.append(
            {
                "path": str(path.relative_to(PROJECT_ROOT)),
                "url": source_url,
                "title": title,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
        if title in TARGET_PEOPLE_PAGES:
            people_page_count += 1
            for entry in extract_people_entries(
                title,
                source_url,
                text,
            ):
                existing = people_by_url.setdefault(
                    entry["url"],
                    {
                        "category": "person",
                        "series": [],
                        "zh_title": entry["zh_title"],
                        "url": entry["url"],
                    },
                )
                series = existing["series"]
                if entry["series"] not in series:
                    series.append(entry["series"])
        elif title == UNIT_INDEX_TITLE:
            unit_index_count += 1
            for entry in extract_unit_entries(text):
                units.setdefault(entry["url"], entry)
        elif "/srwz-details/" in str(path):
            details.append(
                extract_detail_facts(title, source_url, text)
            )

    if people_page_count != 5:
        raise ValueError(
            f"expected 5 SRWZ Gundam people pages, found {people_page_count}"
        )
    if unit_index_count != 1:
        raise ValueError(
            f"expected one Biligame unit index, found {unit_index_count}"
        )

    people = sorted(
        people_by_url.values(),
        key=lambda entry: (entry["zh_title"], entry["url"]),
    )
    unit_entries = sorted(
        units.values(),
        key=lambda entry: (entry["zh_title"], entry["url"]),
    )
    details.sort(key=lambda entry: (entry["title"], entry["url"]))
    pages.sort(key=lambda entry: entry["url"])
    aggregate = hashlib.sha256()
    for page in pages:
        aggregate.update(page["url"].encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(page["sha256"].encode("ascii"))
        aggregate.update(b"\n")
    return {
        "schema_version": 1,
        "reference_id": "biligame-srwz-gundam-index-v1",
        "scope": {
            "franchise_family": "Gundam",
            "srwz_series": [
                "机动战士Z高达",
                "机动战士高达SEED",
                "机动战士高达SEED DESTINY",
                "机动新世纪高达X",
                "逆A高达",
            ],
            "usage": "review_only",
            "auto_apply": False,
        },
        "source": {
            "site": "Biligame Gundam Wiki",
            "fetcher": "Jina Reader",
            "page_count": len(pages),
            "people_page_count": people_page_count,
            "unit_index_count": unit_index_count,
            "detail_page_count": len(details),
            "aggregate_sha256": aggregate.hexdigest(),
            "pages": pages,
        },
        "counts": {
            "unique_person_count": len(people),
            "live_unit_index_entry_count": len(unit_entries),
            "detail_fact_count": len(details),
        },
        "people": people,
        "units": unit_entries,
        "details": details,
    }


def write_tsv(
    path: Path,
    people: Iterable[Mapping[str, object]],
    units: Iterable[Mapping[str, object]],
) -> None:
    fields = ["category", "series", "zh_title", "url"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        for entry in people:
            row = dict(entry)
            row["series"] = "|".join(row.get("series", []))
            writer.writerow({field: row.get(field, "") for field in fields})
        for entry in units:
            writer.writerow({field: entry.get(field, "") for field in fields})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        type=Path,
        default=DEFAULT_SOURCE_ROOT,
    )
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--tsv", type=Path, default=DEFAULT_TSV)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_reference(args.source_root)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_tsv(args.tsv, report["people"], report["units"])
    print(
        json.dumps(
            {
                "status": "passed",
                **report["counts"],
                "page_count": report["source"]["page_count"],
                "report": str(args.report),
                "tsv": str(args.tsv),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
