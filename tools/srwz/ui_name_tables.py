"""Fixed-slot names omitted from the squad-suggestion and map-name tables."""

from __future__ import annotations

import hashlib
import struct

from .codec import decode_production, reencode_changed_suffix
from .iso_layout import ExecutableOffsetSpec, read_executable_archive_offsets
from .text import PreparedTextEncoder, decode_text, project_runtime_text_table


NISV_SPEC = ExecutableOffsetSpec("NISV names", "DATA/NISVDATA.BIN", 0x328E90, 0x328EAC)
SQUAD_COUNT = 104
MAP_INDICES = tuple(i for i in range(1, 75) if i != 5)


def _require(condition, message):
    if not condition:
        raise ValueError("UI name tables: " + message)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def name_slots(source, entries, *, kind, table):
    """Validate complete ownership and original text before returning slots."""
    if kind == "squad":
        _require(len(source) == 29792, "squad decoded size drift")
        _require(struct.unpack_from("<H", source, 0x20)[0] == SQUAD_COUNT,
                 "squad count drift")
        indices, base, stride, capacity = tuple(range(SQUAD_COUNT)), 0x22, 286, 28
    elif kind == "map":
        _require(len(source) == 195 * 256, "map-name file size drift")
        indices, base, stride, capacity = MAP_INDICES, 0, 256, 256
    else:
        raise ValueError("unknown name table kind")
    _require([r["index"] for r in entries] == list(indices),
             f"{kind} missing, duplicated or reordered records")
    slots = []
    for row in entries:
        offset = base + row["index"] * stride
        original = decode_text(source, offset, table, end=offset + capacity)
        _require(original.terminator == "nul" and not original.unknown_code_count and original.text == row["source"],
                 f"{kind}/{row['index']} original text drift")
        _require(row["source_text_sha256"] == _sha(row["source"].encode("utf-8")),
                 "source text hash drift")
        translation = row["translation"]
        _require(row["editorial_status"] == "reviewed" and isinstance(translation, str)
                 and translation and not any(c in translation for c in "\n\r\0{}<>"),
                 "unreviewed or invalid name")
        slots.append((offset, capacity, row))
    return slots


def translate_names(source, current, entries, *, kind, table, overrides):
    """Write names only; all condition IDs, placeholders and padding stay exact."""
    _require(len(source) == len(current), f"{kind} current size drift")
    encoder = PreparedTextEncoder(table, overrides)
    runtime = project_runtime_text_table(table, overrides)
    output = bytearray(current)
    preserved_source, preserved_current = bytearray(source), bytearray(current)
    rows = []
    for offset, capacity, row in name_slots(source, entries, kind=kind, table=table):
        encoded = encoder.encode(row["translation"].replace(" ", "\u3000"), terminate=True)
        _require(len(encoded) <= capacity, f"{kind}/{row['index']} name exceeds {capacity} bytes")
        replacement = encoded + bytes(capacity - len(encoded))
        old = current[offset:offset + capacity]
        _require(old in (source[offset:offset + capacity], replacement),
                 f"{kind}/{row['index']} unexpected current preimage")
        output[offset:offset + capacity] = replacement
        preserved_source[offset:offset + capacity] = bytes(capacity)
        preserved_current[offset:offset + capacity] = bytes(capacity)
        _require(decode_text(output, offset, runtime, end=offset + capacity).text
                 == row["translation"].replace(" ", "\u3000"), "name reread mismatch")
        rows.append({"index": row["index"], "offset": offset, "capacity": capacity,
                     "encoded_size": len(encoded), "translation": row["translation"]})
    _require(preserved_source == preserved_current, f"{kind} non-name data drift")
    return bytes(output), {"entry_count": len(rows), "rows": rows,
                           "non_name_bytes_preserved": True, "translated_reread_exact": True}


def build_ui_name_tables(archive, original_archive, slps, original_map, config, corpus,
                         table, overrides):
    _require(corpus.get("source_authority") == "original_disc_only", "source policy drift")
    offsets = read_executable_archive_offsets(slps, NISV_SPEC, len(archive))
    start, end = offsets[4:6]
    stored = original_archive[start:end]
    decoded = decode_production(stored)
    _require(_sha(decoded.output) == config["squad_decoded_sha256"], "squad source hash drift")
    _require(not any(stored[decoded.consumed:]), "source compression padding drift")
    current = decode_production(archive[start:end])
    _require(not any(archive[start + current.consumed:end]), "current compression padding drift")
    modified, squad_report = translate_names(
        decoded.output, current.output, corpus["squad_names"], kind="squad",
        table=table, overrides=overrides,
    )
    codec = config["codec"]
    encoded = reencode_changed_suffix(
        stored[:decoded.consumed], modified, strategy=codec["strategy"],
        min_match_length=codec["min_match_length"], max_match_chain=codec["max_match_chain"],
        lazy_matching=codec["lazy_matching"], max_output_size=len(stored),
    )
    reread = decode_production(encoded)
    _require(reread.output == modified and reread.consumed == len(encoded),
             "squad compression roundtrip failed")
    output_archive = archive[:start] + encoded + bytes(end - start - len(encoded)) + archive[end:]
    _require(len(output_archive) == len(archive), "archive capacity changed")
    output_map, map_report = translate_names(
        original_map, original_map, corpus["map_names"], kind="map", table=table, overrides=overrides,
    )
    return output_archive, output_map, {
        "squad_names": squad_report, "map_names": map_report,
        "squad_chunk": 4, "squad_decoded_sha256": _sha(modified),
        "squad_stored_size": len(stored), "squad_encoded_size": len(encoded),
        "archive_offsets_preserved": True, "non_target_chunks_preserved": True,
        "map_placeholder_count_preserved": 122,
    }


def verify_name_table(source, actual, entries, *, kind, source_table, runtime_table):
    """Independent readback without using the writer or regenerating output bytes."""
    _require(len(source) == len(actual), f"{kind} readback size drift")
    before, after = bytearray(source), bytearray(actual)
    for offset, capacity, row in name_slots(source, entries, kind=kind, table=source_table):
        text = decode_text(actual, offset, runtime_table, end=offset + capacity)
        _require(text.text == row["translation"].replace(" ", "\u3000") and not text.unknown_code_count,
                 f"{kind}/{row['index']} final ISO text mismatch")
        _require(not any(actual[text.end:offset + capacity]), "nonzero name-slot padding")
        before[offset:offset + capacity] = bytes(capacity)
        after[offset:offset + capacity] = bytes(capacity)
    _require(before == after, f"{kind} final non-name bytes changed")
    return {"entry_count": len(entries), "translated_reread_exact": True,
            "non_name_bytes_preserved": True}
