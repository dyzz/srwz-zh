"""Reproducible controls for separating COMPDATA bytes from ISO layout."""

from __future__ import annotations

from .codec import decode
from .font import sha256_bytes


def build_one_sector_shift_control(
    source: bytes,
    *,
    sector_size: int = 2048,
) -> tuple[bytes, dict]:
    """Append the minimum zero tail that moves a stream into one more sector."""

    if sector_size <= 0:
        raise ValueError("sector size must be positive")
    decoded = decode(source)
    if decoded.consumed != len(source):
        raise ValueError("source stream must be fully consumed")
    source_sectors = (len(source) + sector_size - 1) // sector_size
    padding_size = source_sectors * sector_size - len(source) + 1
    candidate = source + bytes(padding_size)
    candidate_decoded = decode(candidate)
    candidate_sectors = (
        len(candidate) + sector_size - 1
    ) // sector_size
    if (
        candidate_decoded.output != decoded.output
        or candidate_decoded.consumed != len(source)
        or candidate_sectors != source_sectors + 1
    ):
        raise ValueError("LBA shift control invariant failed")
    return candidate, {
        "source_size": len(source),
        "source_sha256": sha256_bytes(source),
        "source_sectors": source_sectors,
        "candidate_size": len(candidate),
        "candidate_sha256": sha256_bytes(candidate),
        "candidate_sectors": candidate_sectors,
        "zero_tail_size": padding_size,
        "compressed_stream_consumed": candidate_decoded.consumed,
        "decoded_size": len(decoded.output),
        "decoded_sha256": sha256_bytes(decoded.output),
        "compressed_stream_bytes_exact": candidate[: len(source)] == source,
        "decoded_bytes_exact": candidate_decoded.output == decoded.output,
    }


__all__ = ["build_one_sector_shift_control"]
