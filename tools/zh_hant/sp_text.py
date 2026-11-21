"""Readable form of SP stored strings in a codebook: characters for codebook codes, printable ASCII as itself,
every other byte below 0x80 as {XX}, an unknown two-byte code as {XXXX}. encode() is the exact inverse."""
from __future__ import annotations

import json
import re
from pathlib import Path


def codebook(path: Path) -> tuple[dict, dict]:
    """(code -> character, character -> code) of a release codebook ledger (primary rows first)."""
    led = json.loads(Path(path).read_text(encoding='utf-8'))
    char_of, code_of = {}, {}
    for k in ('primary_assignments', 'assignments', 'surface_alias_assignments', 'source_compatibility_assignments'):
        for r in led.get(k, []):
            for c in (r.get('code'), r.get('primary_code'), r.get('alias_code')):
                if c:
                    char_of.setdefault(int(c, 16), r['character'])
            if r.get('code') and k in ('primary_assignments', 'assignments'):
                code_of.setdefault(r['character'], int(r['code'], 16))
    return char_of, code_of


def decode(data: bytes, char_of: dict, code_of: dict) -> str:
    out, i = [], 0
    while i < len(data):
        b = data[i]
        if b < 0x80:
            out.append(chr(b) if 0x20 <= b < 0x7F and chr(b) not in '{}' else '{%02X}' % b); i += 1; continue
        code = int.from_bytes(data[i:i + 2], 'big'); ch = char_of.get(code)
        readable = ch and len(ch) == 1 and ord(ch) >= 0x80 and code_of.get(ch) == code   # aliases and ASCII-looking codes stay escaped
        out.append(ch if readable else '{%04X}' % code); i += 2
    return ''.join(out)


TOKEN = re.compile(r'\{([0-9A-F]{2}|[0-9A-F]{4})\}|(.)', re.S)


def encode(text: str, code_of: dict) -> bytes:
    out = bytearray()
    for m in TOKEN.finditer(text):
        if m.group(1):
            out += bytes.fromhex(m.group(1))
        else:
            c = m.group(2)
            if ord(c) < 0x80:
                out.append(ord(c))
            elif c in code_of:
                out += code_of[c].to_bytes(2, 'big')
            else:
                raise ValueError(f'{c!r} has no code in the codebook')
    return bytes(out)
