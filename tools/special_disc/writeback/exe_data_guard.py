"""Verified SP jump-table words misidentified as Japanese strings.

Offsets belong to SLPS_259.20, not COMPDATA. See
verification/audit_exe_non_text.py for the independent MIPS consumer check.
"""

# file offset: (little-endian code address, table file offset, consumer offset)
NON_TEXT_WORDS = {
    0x3B2060: (0x28E390, 0x3B2030, 0x18EBD4),
    0x3B2088: (0x28F088, 0x3B2070, 0x18F468),
    0x3B3590: (0x2CBA90, 0x3B3580, 0x1CC268),
    0x3B35B0: (0x2CB890, 0x3B35A0, 0x1CBF84),
    0x3B3620: (0x2CF788, 0x3B3610, 0x1CFFC4),
    0x3C0D44: (0x3BB488, 0x3C0D30, 0x2BBDC0),
    0x3C0D48: (0x3BB490, 0x3C0D30, 0x2BBDC0),
}


def require_text_range(offset: int, size: int) -> None:
    """Reject any executable text write overlapping a protected pointer word."""
    for site in NON_TEXT_WORDS:
        if offset < site + 4 and site < offset + size:
            raise ValueError(f"executable text overlaps verified jump-table word at 0x{site:X}")
