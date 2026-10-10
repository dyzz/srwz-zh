"""Restore native width codes in the two pilot-status spirit-cost templates.

The native renderer applies code-sensitive width rules to 8169/8148/816A.
The general menu alias pass introduced in 78d2267 moves those characters to
default-width codes. Restoring their pixels (145c3e1) cannot restore those
rules. Keep the general encoding policy and override only these allocations.
"""
from __future__ import annotations

# The pilot ability page reads these unit-status copies. The separate spirit
# command menu copies deliberately remain out of scope.
# Each native allocation is 16 bytes, including its NUL and zero padding.
EDITIONS = ("original", "best", "sp")
SLOTS = (
    ("unknown-cost", "？？？", (0x345448, 0x345C38, 0x3C0BB8)),
    ("known-cost-frame", "　　　", (0x345458, 0x345C48, 0x3C0BC8)),
)
POLICY = {"mode": "native_spirit_cost_templates", "template_count": 2,
          "native_codes": ["8169", "8148", "8140", "816A"]}
CAPACITY = 16


def _slots(executable: bytes, edition: str):
    if edition not in EDITIONS:
        raise ValueError(f"unsupported spirit-cost edition: {edition}")
    for ident, text, offsets in SLOTS:
        at = offsets[EDITIONS.index(edition)]
        if at + CAPACITY > len(executable):
            raise ValueError(f"spirit-cost slot outside executable: {ident}")
        native = ("（" + text + "）").encode("cp932")
        alias_middle = bytes.fromhex("8FD9" if ident == "unknown-cost" else "8140") * 3
        alias = bytes.fromhex("8FE8") + alias_middle + bytes.fromhex("8FEB")
        native += bytes(CAPACITY - len(native))
        alias += bytes(CAPACITY - len(alias))
        actual = executable[at:at + CAPACITY]
        if actual not in (native, alias):
            raise ValueError(f"spirit-cost allocation drift: {ident}")
        yield ident, at, actual, native


def verify_spirit_cost_templates(executable: bytes, edition: str = "original") -> dict:
    rows = []
    for ident, at, actual, native in _slots(executable, edition):
        if actual != native:
            raise ValueError(f"spirit-cost template is not native: {ident}")
        rows.append({"id": ident, "file_offset": hex(at),
                     "allocation_size": CAPACITY, "output_hex": native.hex()})
    return {"edition": edition, "template_count": len(rows), "templates": rows,
            "all_native_templates_exact": True}


def apply_spirit_cost_templates(executable: bytes, edition: str = "original", *,
                                policy: dict | None = None) -> tuple[bytes, dict]:
    if policy is not None and policy != POLICY:
        raise ValueError("spirit-cost policy drift")
    output = bytearray(executable)
    changed = []
    for _ident, at, actual, native in _slots(executable, edition):
        changed.extend(at + i for i, (a, b) in enumerate(zip(actual, native)) if a != b)
        output[at:at + CAPACITY] = native
    result = bytes(output)
    return result, {**verify_spirit_cost_templates(result, edition),
                    "changed_byte_count": len(changed),
                    "changed_offsets": [hex(at) for at in changed],
                    "executable_size_preserved": len(result) == len(executable),
                    "non_target_bytes_preserved": True}
