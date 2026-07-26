"""Parser for the fixed-width Shift-JIS records in ``MAP/MAPNAME.BIN``."""

from __future__ import annotations

from dataclasses import dataclass


MAP_NAME_RECORD_SIZE = 256


class MapNameError(ValueError):
    """The MAPNAME member does not satisfy its fixed-record contract."""


@dataclass(frozen=True)
class MapNameRecord:
    stable_id: str
    index: int
    offset: int
    allocated_size: int
    encoded_size: int
    text: str


def parse_map_names(data: bytes | bytearray | memoryview) -> tuple[MapNameRecord, ...]:
    source = memoryview(data).cast("B").tobytes()
    if not source:
        raise MapNameError("MAPNAME member is empty")
    if len(source) % MAP_NAME_RECORD_SIZE:
        raise MapNameError(
            f"MAPNAME size {len(source)} is not divisible by "
            f"{MAP_NAME_RECORD_SIZE}"
        )

    records = []
    for index, offset in enumerate(range(0, len(source), MAP_NAME_RECORD_SIZE)):
        raw = source[offset : offset + MAP_NAME_RECORD_SIZE]
        terminator = raw.find(b"\0")
        if terminator < 0:
            raise MapNameError(f"map name {index} has no NUL terminator")
        if any(raw[terminator + 1 :]):
            raise MapNameError(f"map name {index} has nonzero padding")
        payload = raw[:terminator]
        if not payload:
            raise MapNameError(f"map name {index} is empty")
        try:
            text = payload.decode("shift_jis")
        except UnicodeDecodeError as error:
            raise MapNameError(
                f"map name {index} is not valid Shift-JIS at byte "
                f"{error.start}"
            ) from error
        records.append(
            MapNameRecord(
                stable_id=f"map/name/{index:03d}",
                index=index,
                offset=offset,
                allocated_size=MAP_NAME_RECORD_SIZE,
                encoded_size=len(payload),
                text=text,
            )
        )
    return tuple(records)


__all__ = [
    "MAP_NAME_RECORD_SIZE",
    "MapNameError",
    "MapNameRecord",
    "parse_map_names",
]
