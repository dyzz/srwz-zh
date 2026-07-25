"""Bounded, byte-free diagnostics for SRWZ decoder trace events."""

from __future__ import annotations

from typing import Mapping


class TraceCollector:
    """Collect aggregate statistics and retain only a bounded event prefix."""

    def __init__(self, event_limit: int):
        if event_limit < 0:
            raise ValueError("trace event limit must be non-negative")
        self.event_limit = event_limit
        self.events = []
        self.total_events = 0
        self.block_count = 0
        self.match_count = 0
        self.literal_bytes = 0
        self.advertised_matches = 0
        self.match_bytes = 0
        self.extended_distance_count = 0
        self.extended_length_count = 0
        self.max_literal_run = 0
        self.max_match_distance = 0
        self.max_match_length = 0

    @property
    def truncated(self) -> bool:
        return self.total_events > len(self.events)

    def __call__(self, event: Mapping[str, object]) -> None:
        self.total_events += 1
        kind = event["kind"]
        if kind == "block":
            literal_count = int(event["literal_count"])
            match_count = int(event["match_count"])
            self.block_count += 1
            self.literal_bytes += literal_count
            self.advertised_matches += match_count
            self.max_literal_run = max(self.max_literal_run, literal_count)
        elif kind == "match":
            distance = int(event["distance"])
            length = int(event["length"])
            self.match_count += 1
            self.match_bytes += length
            self.max_match_distance = max(self.max_match_distance, distance)
            self.max_match_length = max(self.max_match_length, length)
            self.extended_distance_count += int(bool(event["distance_extended"]))
            self.extended_length_count += int(bool(event["length_extended"]))

        if len(self.events) < self.event_limit:
            self.events.append(dict(event))

    def statistics(self) -> dict:
        return {
            "block_count": self.block_count,
            "match_token_count": self.match_count,
            "advertised_match_count": self.advertised_matches,
            "literal_bytes": self.literal_bytes,
            "match_bytes": self.match_bytes,
            "extended_distance_count": self.extended_distance_count,
            "extended_length_count": self.extended_length_count,
            "max_literal_run": self.max_literal_run,
            "max_match_distance": self.max_match_distance,
            "max_match_length": self.max_match_length,
        }

    def bounded_trace(self) -> dict:
        return {
            "event_limit": self.event_limit,
            "total_event_count": self.total_events,
            "truncated": self.truncated,
            "events": self.events,
        }


def require_work_output(path, work_root):
    """Resolve an output path and reject destinations outside ignored work/."""

    resolved = path.resolve()
    work = work_root.resolve()
    try:
        resolved.relative_to(work)
    except ValueError as error:
        raise ValueError(f"diagnostic JSON output must stay under {work}") from error
    return resolved


__all__ = ["TraceCollector", "require_work_output"]
