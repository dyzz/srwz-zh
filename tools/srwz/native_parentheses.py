"""Copy native fullwidth parentheses into their existing localized slots."""

from .font import GLYPH_SIZE, sha256_bytes, standard_glyph_index

SOURCE_CODES = {"（": 0x8169, "）": 0x816A}


def replace_parenthesis_slots(font: bytes, original_font: bytes, assignments: list[dict]):
    if len(font) != len(original_font) or len(font) % GLYPH_SIZE:
        raise ValueError("parenthesis font geometry mismatch")
    targets = {}
    for row in assignments:
        if row["character"] in SOURCE_CODES:
            index = row["glyph_index"]
            if index in targets and targets[index] != row["character"]:
                raise ValueError("shared parenthesis slot")
            targets[index] = row["character"]
    if set(targets.values()) != set(SOURCE_CODES):
        raise ValueError("missing parenthesis assignments")
    if any(row["glyph_index"] in targets and row["character"] != targets[row["glyph_index"]]
           for row in assignments):
        raise ValueError("shared non-parenthesis slot")
    result = bytearray(font)
    changed, copies = [], []
    for index, character in sorted(targets.items()):
        start = index * GLYPH_SIZE
        if not 0 <= start <= len(font) - GLYPH_SIZE:
            raise ValueError("parenthesis slot outside font")
        code = SOURCE_CODES[character]
        source = standard_glyph_index(code) * GLYPH_SIZE
        packed = original_font[source:source + GLYPH_SIZE]
        if len(packed) != GLYPH_SIZE or not any(packed):
            raise ValueError("native parenthesis glyph is blank or absent")
        if result[start:start + GLYPH_SIZE] != packed:
            changed.append(index)
            result[start:start + GLYPH_SIZE] = packed
        copies.append({"character": character, "glyph_index": index,
                       "source_code": f"{code:04X}",
                       "packed_glyph_sha256": sha256_bytes(packed)})
    return bytes(result), {"mode": "copy_original_sp_parentheses",
                           "changed_glyphs": changed, "copies": copies}
