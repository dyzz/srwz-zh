"""Read-only discovery and planning for SRWZ UI memory-card fixtures."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Iterable

from .ui_runtime_matrix import audit_ui_runtime_matrix


_PAGE_DATA_SIZE = 512
_PAGE_SPARE_SIZE = 16
_RAW_PAGE_SIZE = _PAGE_DATA_SIZE + _PAGE_SPARE_SIZE
_FORMAT_SIGNATURE = b"Sony PS2 Memory Card Format"
_TARGET_MARKERS = (
    b"SLPS-25887",
    b"BISLPS-25887",
    b"SLPS_258.87",
    b"SLPS25887",
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _logical_data(raw: bytes) -> tuple[str, bytes] | None:
    if raw and len(raw) % _RAW_PAGE_SIZE == 0:
        return (
            "528-byte-pages",
            b"".join(
                raw[offset : offset + _PAGE_DATA_SIZE]
                for offset in range(0, len(raw), _RAW_PAGE_SIZE)
            ),
        )
    if raw and len(raw) % _PAGE_DATA_SIZE == 0:
        return ("512-byte-pages", raw)
    return None


def inspect_memory_card(path: Path) -> dict:
    """Classify a PCSX2 memory-card image without modifying it."""

    path = path.resolve()
    raw = path.read_bytes()
    layout = _logical_data(raw)
    all_ff = bool(raw) and all(value == 0xFF for value in raw)
    formatted = False
    marker_hits: list[str] = []
    logical_size = None
    layout_name = None
    if layout is not None:
        layout_name, data = layout
        logical_size = len(data)
        formatted = data.startswith(_FORMAT_SIGNATURE)
        marker_hits = [
            marker.decode("ascii")
            for marker in _TARGET_MARKERS
            if marker in data
        ]

    if all_ff:
        classification = "erased_unformatted"
    elif layout is None:
        classification = "unsupported_layout"
    elif formatted and marker_hits:
        classification = "formatted_target_save_candidate"
    elif formatted:
        classification = "formatted_no_target_marker"
    else:
        classification = "unrecognized_memory_card"

    return {
        "path": str(path),
        "size": len(raw),
        "sha256": _sha256(raw),
        "layout": layout_name,
        "logical_size": logical_size,
        "all_ff": all_ff,
        "formatted": formatted,
        "target_marker_hits": marker_hits,
        "classification": classification,
        "target_save_candidate": (
            classification == "formatted_target_save_candidate"
        ),
    }


def discover_memory_cards(search_roots: Iterable[Path]) -> list[dict]:
    """Inspect every unique .ps2 file below the supplied roots."""

    paths: set[Path] = set()
    for raw_root in search_roots:
        root = raw_root.expanduser().resolve()
        if root.is_file() and root.suffix.lower() == ".ps2":
            paths.add(root)
        elif root.is_dir():
            paths.update(
                path.resolve()
                for path in root.rglob("*.ps2")
                if path.is_file()
            )
    candidates = [
        inspect_memory_card(path)
        for path in sorted(paths, key=lambda value: str(value))
    ]
    duplicate_counts = Counter(
        candidate["sha256"] for candidate in candidates
    )
    for candidate in candidates:
        candidate["identical_file_count"] = duplicate_counts[
            candidate["sha256"]
        ]
    return candidates


def _fixture_priorities(report: dict, config: dict) -> list[dict]:
    fixtures = {
        fixture["fixture_id"]: fixture
        for fixture in report["fixtures"]
        if fixture["kind"] == "memory_card"
    }
    requirements = {
        fixture["fixture_id"]: fixture["requirements"]
        for fixture in config["fixtures"]
        if fixture["kind"] == "memory_card"
    }
    grouped_cases: dict[str, list[dict]] = {
        fixture_id: [] for fixture_id in fixtures
    }
    for case in report["cases"]:
        fixture_id = case["fixture_id"]
        if fixture_id in grouped_cases:
            grouped_cases[fixture_id].append(case)

    priorities = []
    for fixture_id, fixture in fixtures.items():
        cases = grouped_cases[fixture_id]
        capture_counts: Counter[str] = Counter()
        for case in cases:
            capture_counts.update(case["capture_counts"])
        priorities.append(
            {
                "fixture_id": fixture_id,
                "status": fixture["status"],
                "workspace_path": fixture["workspace_path"],
                "sha256": fixture["sha256"],
                "requirements": requirements[fixture_id],
                "blocked_case_count": sum(
                    case["execution_readiness"]
                    == "blocked_by_missing_fixture"
                    for case in cases
                ),
                "case_ids": [case["case_id"] for case in cases],
                "scene_ids": sorted(
                    {
                        scene_id
                        for case in cases
                        for scene_id in case["scene_ids"]
                    }
                ),
                "capture_counts": dict(sorted(capture_counts.items())),
                "capture_count": sum(capture_counts.values()),
            }
        )
    priorities.sort(
        key=lambda item: (
            -item["blocked_case_count"],
            -item["capture_count"],
            item["fixture_id"],
        )
    )
    for rank, fixture in enumerate(priorities, start=1):
        fixture["acquisition_rank"] = rank
    return priorities


def build_runtime_fixture_preflight(
    project_root: Path,
    matrix_path: Path,
    search_roots: Iterable[Path],
) -> dict:
    """Combine the reviewed matrix with read-only local card discovery."""

    project_root = project_root.resolve()
    matrix_path = matrix_path.resolve()
    matrix_report = audit_ui_runtime_matrix(project_root, matrix_path)
    config = json.loads(matrix_path.read_text(encoding="utf-8"))
    candidates = discover_memory_cards(search_roots)
    priorities = _fixture_priorities(matrix_report, config)
    memory_fixtures = [
        fixture
        for fixture in matrix_report["fixtures"]
        if fixture["kind"] == "memory_card"
    ]
    not_acquired = [
        fixture
        for fixture in memory_fixtures
        if fixture["status"] == "not_acquired"
    ]
    target_candidates = [
        candidate
        for candidate in candidates
        if candidate["target_save_candidate"]
    ]
    return {
        "schema_version": 1,
        "status": (
            "fixture_inventory_ready"
            if not not_acquired
            else "fixture_acquisition_required"
        ),
        "matrix": {
            "matrix_id": matrix_report["matrix_id"],
            "config": matrix_report["matrix_config"],
            "plan_sha256": matrix_report["matrix_plan_sha256"],
        },
        "summary": {
            "memory_card_fixture_count": len(memory_fixtures),
            "ready_memory_card_fixture_count": (
                len(memory_fixtures) - len(not_acquired)
            ),
            "not_acquired_memory_card_fixture_count": len(not_acquired),
            "blocked_case_count": matrix_report["summary"][
                "missing_fixture_case_count"
            ],
            "candidate_file_count": len(candidates),
            "unique_candidate_hash_count": len(
                {candidate["sha256"] for candidate in candidates}
            ),
            "target_save_candidate_count": len(target_candidates),
        },
        "fixture_priorities": priorities,
        "local_candidates": candidates,
        "boundary": {
            "read_only": True,
            "files_copied": 0,
            "runtime_status": "not_tested",
            "candidate_limit": (
                "A formatted card containing an SLPS-25887 marker is only "
                "a discovery candidate. It does not prove the required "
                "in-game progress state and cannot make a fixture ready."
            ),
        },
    }
