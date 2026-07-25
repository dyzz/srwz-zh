"""Normalize existing upstream XML outputs for exact parser comparison."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path


def _integers(value):
    if value in (None, ""):
        return ()
    return tuple(
        int(part.strip())
        for part in value.split(",")
        if part.strip()
    )


def menu_reference_signature(path: Path) -> tuple:
    root = ET.parse(path).getroot()
    entries = []
    for section_node in root.findall("Strings"):
        section = section_node.findtext("Section") or ""
        for entry in section_node.findall("Entry"):
            embedded = entry.find("EmbedOffset")
            high = () if embedded is None else _integers(embedded.findtext("hi"))
            low = () if embedded is None else _integers(embedded.findtext("lo"))
            entries.append(
                (
                    section,
                    entry.findtext("JapaneseText") or "",
                    _integers(entry.findtext("PointerOffset")),
                    high,
                    low,
                )
            )
    return tuple(entries)


def story_reference_signature(path: Path) -> tuple:
    root = ET.parse(path).getroot()
    entries = []
    speakers = root.find("Speakers")
    if speakers is not None:
        section = speakers.findtext("Section") or "Speaker"
        for entry in speakers.findall("Entry"):
            entries.append(
                (
                    "speaker",
                    section,
                    entry.findtext("JapaneseText") or "",
                    None,
                    int(entry.findtext("Id")),
                )
            )
    for section_node in root.findall("Strings"):
        section = section_node.findtext("Section") or ""
        kind = "condition" if section.startswith("_") else "dialogue"
        for entry in section_node.findall("Entry"):
            pointer = entry.findtext("PointerOffset")
            speaker = entry.findtext("SpeakerId")
            entries.append(
                (
                    kind,
                    section,
                    entry.findtext("JapaneseText") or "",
                    None if pointer in (None, "") else int(pointer),
                    None if speaker in (None, "") else int(speaker),
                )
            )
    return tuple(entries)


def summary_reference_signature(path: Path) -> tuple:
    root = ET.parse(path).getroot()
    return tuple(
        (
            entry.findtext("JapaneseText") or "",
            int(entry.findtext("PointerOffset")),
        )
        for entry in root.findall(".//Entry")
    )


def compare_signatures(actual: tuple, expected: tuple) -> dict:
    first_mismatch = None
    for index, (actual_entry, expected_entry) in enumerate(
        zip(actual, expected)
    ):
        if actual_entry != expected_entry:
            first_mismatch = index
            break
    if first_mismatch is None and len(actual) != len(expected):
        first_mismatch = min(len(actual), len(expected))
    differing = sum(
        actual_entry != expected_entry
        for actual_entry, expected_entry in zip(actual, expected)
    ) + abs(len(actual) - len(expected))
    return {
        "exact": actual == expected,
        "actual_count": len(actual),
        "expected_count": len(expected),
        "differing_entry_count": differing,
        "first_mismatch": first_mismatch,
    }


__all__ = [
    "compare_signatures",
    "menu_reference_signature",
    "story_reference_signature",
    "summary_reference_signature",
]
