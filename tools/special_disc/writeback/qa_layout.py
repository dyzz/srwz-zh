"""Refresh reviewed shared Q&A pages without replacing SP-specific answers."""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

from srwz.codec import decode_production, reencode_changed_suffix
from srwz.nisv_strategy_qa import build_nisv_strategy_qa, _parse_page

ROOT = Path(__file__).resolve().parents[3]
MEMBER = 'DATA/NISVDATA.BIN'
PAGES = (12,)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def compile_original(table, overrides):
    """Use the production writer and its locked Original inputs, not a stale build."""
    config = json.loads((ROOT / 'config/full-story-components.json').read_text())['nisv_strategy_qa']
    corpus_path = ROOT / config['corpus']['path']
    corpus = json.loads(corpus_path.read_text())
    original = (ROOT / config['original_archive']['path']).read_bytes()
    require(sha(original) == config['original_archive']['sha256'], 'Q&A Original archive drift')
    exe = (ROOT / 'work/disc/SLPS_258.87').read_bytes()
    # SP's reviewed snapshot keeps its existing layout profile. Main-game
    # table polishing must not silently change the already accepted SP image.
    archive, report = build_nisv_strategy_qa(original, original, exe, config, corpus, table, overrides,
                                           typography_profile="sp-reviewed-v1")
    a, b = config['target']['stored_start'], config['target']['stored_end']
    return decode_production(original[a:b]).output, decode_production(archive[a:b]).output, dict(
        corpus=dict(path=config['corpus']['path'], sha256=sha(corpus_path.read_bytes())),
        original_archive=config['original_archive'], translated_reread_exact=report['translated_reread_exact'])


def page(chunk, number):
    count, base = struct.unpack_from('<II', chunk)
    require(0 < number < count, 'Q&A page outside allocation table')
    offset, size = struct.unpack_from('<II', chunk, 8 + number * 8)
    return _parse_page(chunk, base + offset, size)


def apply_qa_layout(archive, exe, source, table, overrides):
    """Replace only explicitly reviewed pages whose SP Japanese is Original-exact."""
    a, b = struct.unpack_from('<II', exe, 0x384A00 + 6 * 4)
    require(0 < a < b <= len(archive) == len(source), 'SP Q&A slot drift')
    original_jp, original_zh, inputs = compile_original(table, overrides)
    sp_jp = decode_production(source[a:b]).output
    decoded = decode_production(archive[a:b])
    output = bytearray(decoded.output)
    changed = []
    for number in PAGES:
        jp, sp, zh, current = [page(chunk, number) for chunk in
                              (original_jp, sp_jp, original_zh, decoded.output)]
        jp_blob = original_jp[jp['start']:jp['start'] + jp['size']]
        require(sp_jp[sp['start']:sp['start'] + sp['size']] == jp_blob,
                f'SP Q&A page {number} differs from Original; translation review required')
        require(current['size'] == zh['size'] and current['sprite_bytes'] == zh['sprite_bytes'],
                f'SP Q&A page {number} allocation/sprite drift')
        # Redistribution may cross record boundaries, but never a colour change.
        def styled_runs(records):
            runs = []
            for r in records:
                if not r['raw']:
                    continue
                style = (r['style0'], r['style1'], r['z'])
                if runs and runs[-1][0] == style:
                    runs[-1] = (style, runs[-1][1] + r['raw'])
                else:
                    runs.append((style, r['raw']))
            return runs
        require(styled_runs(current['records']) == styled_runs(zh['records']),
                f'SP Q&A page {number} translated text/style drift')
        replacement = original_zh[zh['start']:zh['start'] + zh['size']]
        start, size = current['start'], current['size']
        if output[start:start + size] != replacement:
            output[start:start + size] = replacement
            changed.append(number)
    if changed:
        packed = reencode_changed_suffix(archive[a:b], bytes(output), strategy='rust-maximum',
                                         max_output_size=b-a, original_result=decoded)
        require(len(packed) <= b-a and decode_production(packed).output == output,
                'SP Q&A compression/readback failed')
        result = archive[:a] + packed + bytes(b-a-len(packed)) + archive[b:]
    else:
        result = archive
    return result, dict(pages=list(PAGES), changed_pages=changed, inputs=inputs,
                        decoded_sha256=sha(output), runtime='pending')
