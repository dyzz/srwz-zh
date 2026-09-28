"""Rebuild SP encyclopedia fields from the current reviewed shared corpus.

The frozen SP canary supplies SP-only fields and binary records. Japanese source
hashes, field kinds and scoped character identities bind shared translations;
no prior main-game build is used as an answer key.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import struct

from build_library_v02_component import BODY_TAGS, load_production_layout, reflow_body
from special_disc.writeback.migrate_library import raw_fields, serialize, sp_offsets
from srwz.codec import decode_production, reencode_changed_suffix
from srwz.library import parse_zkn_decoded_chunk
from srwz.text import encode_text, normalize_original_fullwidth_ascii, two_byte_visible_spaces

ROOT = Path(__file__).resolve().parents[3]
CORPUS = ROOT / 'corpus/zh/library/v0.2-reviewed.json'
CONFIG = ROOT / 'config/library/v0.2-reviewed-writeback.json'
ARCHIVES = {
    'DATA/MTVZKNRT.BIN': ('robot', 'ROBO', 0x387160),
    'DATA/MTVZKNPT.BIN': ('character', 'CHAR', 0x3865B0),
    'DATA/MTVZKNKW.BIN': ('glossary', 'KYWD', 0x387770),
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def translations(corpus):
    if (corpus.get('status') != 'reviewed' or not corpus.get('release_eligible')
            or len(corpus['entries']) != 2709):
        raise ValueError('shared library corpus contract drift')
    rows = {}
    for row in corpus['entries']:
        key = row['source_text_sha256']
        if key in rows or not row['translation']:
            raise ValueError('shared library translation identity drift')
        rows[key] = row
    return rows


def field_translation(rows, scoped, domain, document, field):
    if field.text is None or not field.text.strip():
        return None
    key = sha(field.text.encode('utf-8'))
    row = rows.get(key)
    if row is None:
        return None
    if domain not in row['domains'] or field.tag not in row['tags']:
        return None
    text = row['translation']
    # The main corpus currently has two voice-credit corrections bound to the
    # character's Japanese full name. The main-game numeric index is not an SP ID.
    context = document.field('CHFN').text if document.kind == 'CHAR' else None
    matches = [r for r in scoped if r['source_text_sha256'] == key
               and r['id'].split('/')[0] == domain
               and r['id'].split('/')[-1] == field.tag
               and context is not None
               and r.get('context_text_sha256') == sha(context.encode('utf-8'))]
    if len(matches) > 1:
        raise ValueError('ambiguous shared library scoped translation')
    if matches:
        text = matches[0]['translation']
    return normalize_original_fullwidth_ascii(text)


def authoring():
    corpus = json.loads(CORPUS.read_text())
    config = json.loads(CONFIG.read_text())
    layout = config['layout']
    widths = layout['body_line_widths']
    profiles, terms, profile_path, release_path, glossary_paths = load_production_layout(layout, widths)
    inputs = [CORPUS, CONFIG, profile_path, release_path, *glossary_paths]
    locks = {p.relative_to(ROOT).as_posix(): sha(p.read_bytes()) for p in inputs}
    return translations(corpus), corpus.get('field_translation_overrides', []), widths, profiles, terms, locks


def replacement_fields(native, baseline_decoded, domain, author, table, overrides):
    rows, scoped, widths, profiles, terms, _ = author
    kind, fields = raw_fields(baseline_decoded)
    if (kind != native.kind or [tag for tag, _ in fields] != [f.tag for f in native.fields]):
        raise ValueError('SP library native/canary field identity drift')
    output, counts = [], Counter()
    for (tag, old), field in zip(fields, native.fields):
        if field.text is None:
            if old != field.data:
                raise ValueError('SP library canary binary field drift')
            output.append((tag, old))
            continue
        text = field_translation(rows, scoped, domain, native, field)
        if text is None:
            output.append((tag, old))
            counts['canary_fields_preserved'] += 1
            continue
        if tag in BODY_TAGS:
            text, _ = reflow_body(text, widths[kind], profile=profiles[kind], protected_terms=terms)
            counts['current_body_fields'] += 1
        data = encode_text(two_byte_visible_spaces(text), table, overrides=overrides, terminate=False)
        output.append((tag, data))
        counts['current_shared_fields'] += 1
        counts['fields_changed_from_canary'] += data != old
    return output, counts


def apply_shared_library(executable, current_member, source_member, table, overrides):
    """Return archives + executable with only the three owned offset tables edited."""
    author = authoring()
    original_exe = source_member('SLPS_259.20')
    exe = bytearray(executable)
    outputs, reports = {}, {}
    for member, (domain, kind, start) in ARCHIVES.items():
        base, source = current_member(member), source_member(member)
        offsets = sp_offsets(executable, start, len(base))
        native_offsets = sp_offsets(original_exe, start, len(source))
        if len(offsets) != len(native_offsets):
            raise ValueError('SP library document count drift')
        stored_chunks, counts = [], Counter()
        for index, ((a, b), (c, d)) in enumerate(zip(zip(offsets, offsets[1:]), zip(native_offsets, native_offsets[1:]))):
            old = decode_production(base[a:b])
            native = parse_zkn_decoded_chunk(decode_production(source[c:d]).output)
            if native.kind != kind:
                raise ValueError('SP library document kind drift')
            fields, tally = replacement_fields(native, old.output, domain, author, table, overrides)
            counts.update(tally)
            rebuilt = serialize(kind, native.version, fields)
            if rebuilt == old.output:
                stored = base[a:a + old.consumed]
            else:
                stored = reencode_changed_suffix(base[a:a + old.consumed], rebuilt,
                                                 strategy='rust-fit', original_result=old)
                counts['documents_rewritten'] += 1
            if decode_production(stored).output != rebuilt:
                raise ValueError(f'SP library chunk readback mismatch: {member}/{index}')
            stored_chunks.append(stored)
        output, new_offsets = bytearray(), []
        for blob in stored_chunks:
            new_offsets.append(len(output))
            output.extend(blob)
            output.extend(bytes(-len(output) % 16))
        used = len(output)
        if used > len(base):
            raise ValueError(f'SP library archive allocation exceeded: {member}: {used}>{len(base)}')
        output.extend(bytes(len(base) - used))
        for i, offset in enumerate(new_offsets):
            struct.pack_into('<I', exe, start + 4*i, offset)
        # Preserve the terminal offset (the original physical member budget).
        if sp_offsets(bytes(exe), start, len(output))[:-1] != new_offsets:
            raise ValueError('SP library rebuilt offset table drift')
        outputs[member] = bytes(output)
        reports[member] = dict(documents=len(stored_chunks), used=used, capacity=len(base),
                               native_sha256=sha(source), canary_sha256=sha(base), **counts)
    report = dict(schema_version=1, inputs=author[-1], archives=reports,
                  policy='current_reviewed_shared_fields_with_sp_canary_fallback')
    return bytes(exe), outputs, report


def verify_shared_library(executable, actual_member, baseline_member, source_member, table, overrides, report):
    """Reread every final field against current source and preserved canary fields."""
    author = authoring()
    if author[-1] != report['inputs']:
        raise ValueError('SP current library authoring inputs drift')
    native_exe, base_exe = source_member('SLPS_259.20'), baseline_member('SLPS_259.20')
    counts = Counter()
    for member, (domain, kind, start) in ARCHIVES.items():
        actual, base, source = actual_member(member), baseline_member(member), source_member(member)
        offsets = sp_offsets(executable, start, len(actual))
        old_offsets = sp_offsets(base_exe, start, len(base))
        native_offsets = sp_offsets(native_exe, start, len(source))
        if len(offsets) != len(old_offsets) or len(offsets) != len(native_offsets):
            raise ValueError('SP final library document count drift')
        if sha(source) != report['archives'][member]['native_sha256'] or sha(base) != report['archives'][member]['canary_sha256']:
            raise ValueError('SP final library source/canary identity drift')
        for index in range(len(offsets)-1):
            native = parse_zkn_decoded_chunk(decode_production(source[native_offsets[index]:native_offsets[index+1]]).output)
            baseline = decode_production(base[old_offsets[index]:old_offsets[index+1]]).output
            want, tally = replacement_fields(native, baseline, domain, author, table, overrides)
            got = decode_production(actual[offsets[index]:offsets[index+1]]).output
            if raw_fields(got) != (kind, want):
                raise ValueError(f'SP final library field mismatch: {member}/{index}')
            counts.update(tally)
            counts['documents'] += 1
    return dict(counts)
