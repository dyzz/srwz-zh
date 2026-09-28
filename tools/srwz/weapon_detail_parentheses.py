"""Native-width parentheses for the seven weapon-detail icon templates only."""
from __future__ import annotations

# Native ELF string allocations, audited against each edition's original disc.
# BEST locations follow source-layout.json's piecewise ELF map.
SLOTS = (
    ("map", 3, 32, (0x3454C0, 0x345CB0, 0x3C0C30)),
    ("tri", 3, 32, (0x3454E0, 0x345CD0, 0x3C0C50)),
    ("all", 3, 32, (0x345500, 0x345CF0, 0x3C0C70)),
    ("pla", 3, 32, (0x345520, 0x345D10, 0x3C0C90)),
    ("one-icon", 1, 8, (0x345578, 0x345D68, 0x3C0CE8)),
    ("two-icons", 2, 16, (0x345580, 0x345D70, 0x3C0CF0)),
    ("three-icons", 3, 16, (0x345590, 0x345D80, 0x3C0D00)),
)
EDITIONS = ("original", "best", "sp")
POLICY = {"mode": "native_icon_template_parentheses", "native_codes": ["8169", "816A"], "template_count": 7}


def _templates(executable: bytes, edition: str):
    if edition not in EDITIONS:
        raise ValueError(f"unsupported weapon-detail edition: {edition}")
    index = EDITIONS.index(edition)
    for ident, spaces, capacity, offsets in SLOTS:
        start = offsets[index]
        if start + capacity > len(executable):
            raise ValueError(f"weapon-detail template outside executable: {ident}")
        allocation = executable[start:start + capacity]
        end = allocation.find(b"\0")
        if end < 0:
            raise ValueError(f"unterminated weapon-detail template: {ident}")
        body = allocation[:end]
        native = b"\x81\x69" + b"\x81\x40" * spaces + b"\x81\x6a"
        alias = b"\x8f\xe8" + b"\x81\x40" * spaces + b"\x8f\xeb"
        tail = body[-len(native):]
        placeholder = ident in ("one-icon", "two-icons", "three-icons")
        if tail not in (native, alias) or (placeholder and len(body) != len(native)) or (not placeholder and len(body) <= len(native)):
            raise ValueError(f"weapon-detail template suffix drift: {ident}")
        yield ident, start, body, start + len(body) - len(native), native


def verify_weapon_detail_parentheses(executable: bytes, edition: str = "original") -> dict:
    rows = []
    for ident, start, body, at, native in _templates(executable, edition):
        if executable[at:at + len(native)] != native:
            raise ValueError(f"weapon-detail parentheses are not native: {ident}")
        rows.append({"id": ident, "file_offset": hex(start),
                     "parenthesis_offset": hex(at), "output_hex": body.hex()})
    return {"edition": edition, "template_count": len(rows), "templates": rows,
            "native_codes": ["8169", "816A"], "all_native_templates_exact": True}


def apply_weapon_detail_parentheses(executable: bytes, edition: str = "original", *, policy: dict | None = None) -> tuple[bytes, dict]:
    if policy is not None and policy != POLICY:
        raise ValueError("weapon-detail parenthesis policy drift")
    output = bytearray(executable)
    changed = []
    for _ident, _start, _body, at, native in _templates(executable, edition):
        # Leave all spaces and the Chinese prefix untouched; replace just the
        # two two-byte parentheses. Already-native input is accepted unchanged.
        for pos, code in ((at, native[:2]), (at + len(native) - 2, native[-2:])):
            changed.extend(pos + i for i, byte in enumerate(code)
                           if executable[pos + i] != byte)
            output[pos:pos + 2] = code
    result = bytes(output)
    return result, {**verify_weapon_detail_parentheses(result, edition),
                    "changed_byte_count": len(changed), "changed_offsets": [hex(x) for x in changed],
                    "executable_size_preserved": len(result) == len(executable),
                    "non_target_bytes_preserved": True}
