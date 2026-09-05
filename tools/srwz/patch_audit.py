"""Strict, byte-free audit primitives for binary patch outputs."""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional


class PatchAuditError(ValueError):
    """A binary patch violates its pinned input or allowed-difference contract."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _packed_u32(values: Iterable[int]) -> bytes:
    return b"".join(struct.pack("<I", value) for value in values)


def _as_int(value, *, field: str) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError as error:
            raise PatchAuditError(f"{field} is not an integer") from error
    raise PatchAuditError(f"{field} is not an integer")


@dataclass(frozen=True)
class DiffSummary:
    diff_count: int
    range_count: int
    first_offset: Optional[int]
    last_offset: Optional[int]
    offsets_sha256: str
    ranges_sha256: str
    before_values_sha256: str
    after_values_sha256: str

    def to_mapping(self) -> dict:
        return {
            "diff_count": self.diff_count,
            "range_count": self.range_count,
            "first_offset": self.first_offset,
            "last_offset": self.last_offset,
            "offsets_sha256": self.offsets_sha256,
            "ranges_sha256": self.ranges_sha256,
            "before_values_sha256": self.before_values_sha256,
            "after_values_sha256": self.after_values_sha256,
        }


def changed_offsets(before: bytes, after: bytes) -> tuple[int, ...]:
    if len(before) != len(after):
        raise PatchAuditError("binary patch changes file size")
    # Compare unchanged blocks in C, entering Python only for touched blocks.
    # Large archives commonly change a few small spans; every byte still
    # participates in the comparison and offsets keep their original order.
    offsets = []
    block_size = 4096
    for start in range(0, len(before), block_size):
        old_block = before[start : start + block_size]
        new_block = after[start : start + block_size]
        if old_block != new_block:
            offsets.extend(
                start + index
                for index, (old, new) in enumerate(zip(old_block, new_block))
                if old != new
            )
    return tuple(offsets)


def contiguous_ranges(
    offsets: Iterable[int],
) -> tuple[tuple[int, int], ...]:
    ranges = []
    for offset in offsets:
        if ranges and offset == ranges[-1][1]:
            ranges[-1] = (ranges[-1][0], offset + 1)
        else:
            ranges.append((offset, offset + 1))
    return tuple(ranges)


def summarize_diff(before: bytes, after: bytes) -> DiffSummary:
    offsets = changed_offsets(before, after)
    ranges = contiguous_ranges(offsets)
    return DiffSummary(
        diff_count=len(offsets),
        range_count=len(ranges),
        first_offset=offsets[0] if offsets else None,
        last_offset=offsets[-1] if offsets else None,
        offsets_sha256=sha256_bytes(_packed_u32(offsets)),
        ranges_sha256=sha256_bytes(
            b"".join(
                struct.pack("<II", start, end)
                for start, end in ranges
            )
        ),
        before_values_sha256=sha256_bytes(
            bytes(before[offset] for offset in offsets)
        ),
        after_values_sha256=sha256_bytes(
            bytes(after[offset] for offset in offsets)
        ),
    )


def _check_hash_and_size(
    data: bytes,
    expected: Mapping,
    *,
    context: str,
) -> None:
    size = _as_int(expected.get("size"), field=f"{context}.size")
    if len(data) != size:
        raise PatchAuditError(
            f"{context} size mismatch: expected {size}, got {len(data)}"
        )
    digest = expected.get("sha256")
    if not isinstance(digest, str):
        raise PatchAuditError(f"{context}.sha256 is missing")
    actual = sha256_bytes(data)
    if actual != digest:
        raise PatchAuditError(
            f"{context} SHA-256 mismatch: expected {digest}, got {actual}"
        )


def _check_diff_summary(
    actual: DiffSummary,
    expected: Mapping,
    *,
    context: str,
    require_all: bool = True,
) -> None:
    actual_mapping = actual.to_mapping()
    for field, actual_value in actual_mapping.items():
        if field not in expected:
            if require_all:
                raise PatchAuditError(f"{context}.{field} is missing")
            continue
        expected_value = expected[field]
        if field in {
            "diff_count",
            "range_count",
            "first_offset",
            "last_offset",
        } and expected_value is not None:
            expected_value = _as_int(
                expected_value,
                field=f"{context}.{field}",
            )
        if actual_value != expected_value:
            raise PatchAuditError(
                f"{context}.{field} mismatch: "
                f"expected {expected_value!r}, got {actual_value!r}"
            )


def _allowed_ranges(target: Mapping, *, file_size: int) -> tuple:
    raw_ranges = target.get("allowed_ranges")
    if not isinstance(raw_ranges, list) or not raw_ranges:
        raise PatchAuditError("patch target has no allowed_ranges")
    ranges = []
    for ordinal, raw in enumerate(raw_ranges):
        if not isinstance(raw, dict):
            raise PatchAuditError("allowed range is not an object")
        start = _as_int(
            raw.get("start"),
            field=f"allowed_ranges[{ordinal}].start",
        )
        end = _as_int(
            raw.get("end"),
            field=f"allowed_ranges[{ordinal}].end",
        )
        if not 0 <= start < end <= file_size:
            raise PatchAuditError("allowed range is outside the input")
        owner = raw.get("owner")
        if owner is not None and not isinstance(owner, str):
            raise PatchAuditError("allowed range owner is not a string")
        ranges.append((start, end, owner))
    return tuple(ranges)


def _check_offsets_allowed(
    offsets: Iterable[int],
    ranges: tuple,
    *,
    owner: Optional[str] = None,
) -> None:
    for offset in offsets:
        if not any(
            start <= offset < end
            and (owner is None or range_owner in (None, owner))
            for start, end, range_owner in ranges
        ):
            label = f" for owner {owner}" if owner else ""
            raise PatchAuditError(
                f"write at 0x{offset:X} is outside allowed ranges{label}"
            )


def _offset_digest(offsets: Iterable[int]) -> str:
    return sha256_bytes(_packed_u32(offsets))


def audit_binary_patch(
    before: bytes,
    after: bytes,
    target: Mapping,
    *,
    owner_outputs: Optional[Mapping[str, bytes]] = None,
) -> dict:
    """Audit one output without embedding any source or patched bytes."""

    if not isinstance(target, dict):
        raise PatchAuditError("patch target is not an object")
    _check_hash_and_size(
        before,
        target.get("input", {}),
        context="input",
    )
    _check_hash_and_size(
        after,
        target.get("output", {}),
        context="output",
    )
    if len(before) != len(after):
        raise PatchAuditError("binary patch changes file size")

    summary = summarize_diff(before, after)
    _check_diff_summary(
        summary,
        target.get("expected_diff", {}),
        context="expected_diff",
    )
    final_offsets = changed_offsets(before, after)
    ranges = _allowed_ranges(target, file_size=len(before))
    _check_offsets_allowed(final_offsets, ranges)

    expected_owners = target.get("owners", {})
    supplied_owners = dict(owner_outputs or {})
    if not isinstance(expected_owners, dict):
        raise PatchAuditError("owners contract is not an object")
    if set(supplied_owners) != set(expected_owners):
        missing = sorted(set(expected_owners) - set(supplied_owners))
        extra = sorted(set(supplied_owners) - set(expected_owners))
        raise PatchAuditError(
            f"owner outputs mismatch: missing={missing}, extra={extra}"
        )

    owner_offsets = {}
    owner_reports = {}
    for owner, expected in sorted(expected_owners.items()):
        data = supplied_owners[owner]
        _check_hash_and_size(
            data,
            {
                "size": len(before),
                "sha256": expected.get("output_sha256"),
            },
            context=f"owners.{owner}.output",
        )
        owner_summary = summarize_diff(before, data)
        _check_diff_summary(
            owner_summary,
            expected.get("diff", {}),
            context=f"owners.{owner}.diff",
            require_all=False,
        )
        offsets = changed_offsets(before, data)
        _check_offsets_allowed(offsets, ranges, owner=owner)
        owner_offsets[owner] = frozenset(offsets)
        owner_reports[owner] = {
            "output_sha256": sha256_bytes(data),
            "diff": owner_summary.to_mapping(),
        }

    owner_union = frozenset().union(*owner_offsets.values())
    final_offset_set = frozenset(final_offsets)
    if owner_union != final_offset_set:
        missing = sorted(final_offset_set - owner_union)
        extra = sorted(owner_union - final_offset_set)
        raise PatchAuditError(
            "owner diff union does not equal the final diff set: "
            f"missing={missing}, extra={extra}"
        )

    overlap_groups = {}
    for offset in sorted(owner_union):
        owners = tuple(
            owner
            for owner in sorted(owner_offsets)
            if offset in owner_offsets[owner]
        )
        if expected_owners and not owners:
            raise PatchAuditError(
                f"final write at 0x{offset:X} has no declared owner"
            )
        if owners and not any(
            supplied_owners[owner][offset] == after[offset]
            for owner in owners
        ):
            raise PatchAuditError(
                f"final value at 0x{offset:X} is not produced by an owner"
            )
        if len(owners) > 1:
            overlap_groups.setdefault(owners, []).append(offset)

    raw_allowed_overlaps = target.get("allowed_overlaps", [])
    if not isinstance(raw_allowed_overlaps, list):
        raise PatchAuditError("allowed_overlaps is not an array")
    allowed_overlaps = {}
    for ordinal, rule in enumerate(raw_allowed_overlaps):
        if not isinstance(rule, dict):
            raise PatchAuditError("allowed overlap is not an object")
        owners = rule.get("owners")
        if (
            not isinstance(owners, list)
            or len(owners) < 2
            or any(not isinstance(owner, str) for owner in owners)
        ):
            raise PatchAuditError("allowed overlap owners are invalid")
        key = tuple(sorted(owners))
        if key in allowed_overlaps:
            raise PatchAuditError("duplicate allowed overlap owner set")
        final_owner = rule.get("final_owner")
        if final_owner not in key:
            raise PatchAuditError("allowed overlap final_owner is invalid")
        count = _as_int(
            rule.get("count"),
            field=f"allowed_overlaps[{ordinal}].count",
        )
        digest = rule.get("offsets_sha256")
        if not isinstance(digest, str):
            raise PatchAuditError("allowed overlap digest is missing")
        allowed_overlaps[key] = (count, digest, final_owner)

    if set(overlap_groups) != set(allowed_overlaps):
        unexpected = sorted(set(overlap_groups) - set(allowed_overlaps))
        missing = sorted(set(allowed_overlaps) - set(overlap_groups))
        raise PatchAuditError(
            f"implicit overlap mismatch: unexpected={unexpected}, "
            f"missing={missing}"
        )

    overlap_reports = []
    for owners, offsets in sorted(overlap_groups.items()):
        expected_count, expected_digest, final_owner = allowed_overlaps[
            owners
        ]
        digest = _offset_digest(offsets)
        if len(offsets) != expected_count or digest != expected_digest:
            raise PatchAuditError(
                f"overlap {owners} does not match its exact offset set"
            )
        for offset in offsets:
            if supplied_owners[final_owner][offset] != after[offset]:
                raise PatchAuditError(
                    f"overlap final owner mismatch at 0x{offset:X}"
                )
        overlap_reports.append(
            {
                "owners": list(owners),
                "final_owner": final_owner,
                "count": len(offsets),
                "offsets_sha256": digest,
            }
        )

    return {
        "input": {
            "size": len(before),
            "sha256": sha256_bytes(before),
        },
        "output": {
            "size": len(after),
            "sha256": sha256_bytes(after),
        },
        "diff": summary.to_mapping(),
        "allowed_range_count": len(ranges),
        "owner_count": len(owner_reports),
        "owners": owner_reports,
        "overlaps": overlap_reports,
    }


__all__ = [
    "DiffSummary",
    "PatchAuditError",
    "audit_binary_patch",
    "changed_offsets",
    "contiguous_ranges",
    "sha256_bytes",
    "summarize_diff",
]
