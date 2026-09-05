"""Four Best data corrections for the Original COMPDATA layout.

Offsets refer to decoded data. This never imports Best code, pointers, or
encyclopedia unlock rules. The two encyclopedia IDs are full little-endian u16s.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256


PROFILE_ID = "original-best-compdata-fields-v1"
DECODED_SIZE = 524032
ORIGINAL_BASE = 0x6D6800
PILOT_BASE, PILOT_STRIDE = 0x2160, 0xB0
UNIT_BASE, UNIT_STRIDE = 0x4CAE0, 0x44
ENCYCLOPEDIA_LOOKUP = 0x5AB70
FRANCHISE_LOOKUP = 0x5D2A0


@dataclass(frozen=True)
class FieldCorrection:
    field_id: str
    offset: int
    width: int
    original: int
    best: int


CORRECTIONS = (
    FieldCorrection("pilot/0116/name_format", PILOT_BASE + 116 * PILOT_STRIDE + 0x45, 1, 1, 0),
    FieldCorrection("unit/0800/encyclopedia_id", UNIT_BASE + 800 * UNIT_STRIDE + 0x3E, 2, 315, 316),
    FieldCorrection("unit/0607/encyclopedia_lookup", ENCYCLOPEDIA_LOOKUP + 607 * 2, 2, 254, 252),
    FieldCorrection("unit/0607/franchise_lookup", FRANCHISE_LOOKUP + 607, 1, 18, 17),
)


def _read(data: bytes, offset: int, width: int) -> int:
    return int.from_bytes(data[offset:offset + width], "little")


def _validate_layout(data: bytes, config: dict) -> None:
    if config != {"profile_id": PROFILE_ID}:
        raise ValueError("Best COMPDATA correction profile drift")
    if len(data) != DECODED_SIZE or data[:4] != b"MWo3" or _read(data, 8, 4) != ORIGINAL_BASE:
        raise ValueError("Best COMPDATA corrections require the Original decoded layout")
    # Guard owners and the duplicate associations which Best makes consistent.
    guards = (
        (PILOT_BASE + 116 * PILOT_STRIDE, 2, 116),
        (UNIT_BASE + 800 * UNIT_STRIDE, 2, 800),
        (UNIT_BASE + 607 * UNIT_STRIDE, 2, 607),
        (UNIT_BASE + 607 * UNIT_STRIDE + 0x3E, 2, 252),
        (UNIT_BASE + 607 * UNIT_STRIDE + 0x3D, 1, 17),
        (ENCYCLOPEDIA_LOOKUP + 800 * 2, 2, 316),
        (UNIT_BASE + 800 * UNIT_STRIDE + 0x3D, 1, 21),
        (FRANCHISE_LOOKUP + 800, 1, 21),
    )
    for offset, width, expected in guards:
        if _read(data, offset, width) != expected:
            raise ValueError(f"Best COMPDATA owner/association drift at 0x{offset:X}")


def audit_compdata_best_corrections(data: bytes, config: dict) -> dict:
    """Reject a final component/ISO unless every corrected field reads back."""
    _validate_layout(data, config)
    fields = []
    for field in CORRECTIONS:
        actual = _read(data, field.offset, field.width)
        if actual != field.best:
            raise ValueError(f"Best COMPDATA correction readback mismatch: {field.field_id}: {actual} != {field.best}")
        fields.append({
            "field_id": field.field_id,
            "decoded_offset": f"0x{field.offset:X}",
            "width": field.width,
            "original_value": field.original,
            "corrected_value": actual,
            "original_hex": field.original.to_bytes(field.width, "little").hex(),
            "corrected_hex": actual.to_bytes(field.width, "little").hex(),
        })
    return {
        "profile_id": PROFILE_ID,
        "decoded_size": len(data),
        "runtime_base": f"0x{ORIGINAL_BASE:X}",
        "field_count": len(fields),
        "fields": fields,
        "all_corrected_fields_exact": True,
        "owner_and_duplicate_associations_exact": True,
    }


def apply_compdata_best_corrections(data: bytes, config: dict) -> tuple[bytes, dict]:
    """Apply once after localization, checking all original field preimages."""
    _validate_layout(data, config)
    for field in CORRECTIONS:
        actual = _read(data, field.offset, field.width)
        if actual != field.original:
            raise ValueError(f"Best COMPDATA correction preimage drift: {field.field_id}: {actual} != {field.original}")
    output = bytearray(data)
    for field in CORRECTIONS:
        output[field.offset:field.offset + field.width] = field.best.to_bytes(field.width, "little")
    result = bytes(output)
    changed = [index for index, (old, new) in enumerate(zip(data, result)) if old != new]
    if changed != [0x7165, 0x59F9E, 0x5B02E, 0x5D4FF] or len(result) != len(data):
        raise ValueError("Best COMPDATA corrections escaped the four-byte write scope")
    report = audit_compdata_best_corrections(result, config)
    report.update({
        "source_decoded_sha256": sha256(data).hexdigest(),
        "output_decoded_sha256": sha256(result).hexdigest(),
        "source_preimages_exact": True,
        "changed_byte_count": len(changed),
        "changed_decoded_offsets": [f"0x{offset:X}" for offset in changed],
        "non_target_bytes_exact": True,
        "embedded_code_unchanged": data[0x80:0x8C0] == result[0x80:0x8C0],
        "decoded_size_preserved": True,
    })
    return result, report
