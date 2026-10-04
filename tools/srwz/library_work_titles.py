"""Bounded encyclopedia work-title pool, with all native pointer sites locked.

Auto-demo text remains plain; the encyclopedia table compiles closed PRDC scopes.
Repacking is confined to the native 656-byte pool and its 55 pointer words.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import struct
from .library_typography import library_typography
from .text import encode_text, decode_text, normalize_original_fullwidth_ascii, two_byte_visible_spaces

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / 'config/library/work-title-typography.json'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def compact_library_list_name(text):
    """The D.O.M.E.G-Bit list slot fits a closed advance-only scope (31/32 bytes)."""
    return '<space:0E>' + text + '<space:16>' if text == 'D.O.M.E.G-Bit' else text


def list_name_binding(data, c, readback):
    r = c['compact_list_name'];at = r['offset']
    actual = decode_text(data, at, readback, end=at+r['capacity'])
    require(actual.text == compact_library_list_name(r['translation']) and actual.terminator == 'nul'
            and not any(data[at+actual.consumed:at+r['capacity']]), 'library compact list name final mismatch')
    for site in r['pointer_sites']:
        require(struct.unpack_from('<I',data,site)[0]==c['base']+at,'library compact list name pointer mismatch')
    return dict(offset=at,translation=r['translation'],stored_translation=actual.text,
                capacity=r['capacity'],encoded_size=actual.consumed,pointer_count=len(r['pointer_sites']))


def inputs(edition='original', canonical=None):
    contract = json.loads(CONTRACT.read_text())
    c = contract['variants'][edition]
    corpus = canonical or json.loads((ROOT / contract['canonical_corpus']).read_text())
    rows = {r['id']: r for r in corpus['entries']}
    require(corpus['language'] == 'zh-Hans' and len(rows) == 22 and
            set(rows) == {r['id'] for r in c['entries']}, 'library work title coverage drift')
    for r in rows.values():
        require(r['editorial_status'] == 'reviewed' and r['translation'] and
                r['source_text_sha256'] == sha(r['source_text'].encode()), 'library work title corpus drift')
    require(c['pool_end'] - c['pool_start'] == 656 and
            sum(len(r['pointer_sites']) for r in c['entries']) == 55,
            'library work title pool ownership drift')
    return c, rows


def plan(c, rows, table, overrides):
    pool = bytearray()
    targets = []
    for r in c['entries']:
        text = two_byte_visible_spaces(library_typography(rows[r['id']]['translation'], 'PRDC'))
        payload = encode_text(text, table, overrides=overrides, terminate=True)
        at = c['pool_start'] + len(pool)
        targets.append(dict(id=r['id'], source_offset=r['offset'], offset=at,
                            stored_translation=text, encoded_size=len(payload), pointer_sites=r['pointer_sites']))
        pool.extend(payload)
        pool.extend(bytes(-len(pool) % 2))
    budget = c['pool_end'] - c['pool_start']
    require(len(pool) <= budget, f'library work title pool overflow: {len(pool)}>{budget}')
    used = len(pool)
    pool.extend(bytes(budget-len(pool)))
    return bytes(pool), targets, used


def validate_source(native, c, rows):
    require(len(native) == c['decoded_size'] and sha(native) == c['decoded_sha256'],
            'library work title native COMPDATA drift')
    r = c['compact_list_name'];span=native[r['offset']:r['offset']+r['capacity']]
    source=r['source_text'].encode('cp932')+b'\0'
    require(span == source+bytes(r['capacity']-len(source)), 'library compact list name native drift')
    sites=[site for site in range(0,len(native)-3,4) if struct.unpack_from('<I',native,site)[0]==c['base']+r['offset']]
    require(sites==r['pointer_sites'],'library compact list name reference drift')
    cursor = c['pool_start']
    pointers = {}
    for r in c['entries']:
        require(r['offset'] == cursor, 'library work title source pool gap')
        span = native[cursor:cursor+r['capacity']]
        end = span.find(b'\0')
        require(end > 0 and sha(span) == r['source_span_sha256'] and
                span[:end].decode('cp932') == rows[r['id']]['source_text'] and
                not any(span[end+1:]), 'library work title native preimage drift')
        cursor += r['capacity']
        for site in r['pointer_sites']:
            require(struct.unpack_from('<I',native,site)[0] == c['base']+r['offset'],
                    'library work title source pointer drift')
            pointers[site] = r['offset']
    require(cursor == c['pool_end'], 'library work title pool end drift')
    actual = {site: struct.unpack_from('<I',native,site)[0]-c['base']
              for site in range(0,len(native)-3,4)
              if c['pool_start'] <= struct.unpack_from('<I',native,site)[0]-c['base'] < c['pool_end']}
    require(actual == pointers, 'library work title unowned native reference')


def apply_work_title_pool(current, native, table, overrides, *, edition='original', canonical=None):
    c, rows = inputs(edition,canonical)
    validate_source(native,c,rows)
    require(len(current) == len(native), 'library work title decoded size changed')
    pool, targets, used = plan(c,rows,table,overrides)
    # Accept the native table, the previous reviewed plain table, or our output.
    plain = bytearray()
    for r in c['entries']:
        payload = encode_text(two_byte_visible_spaces(normalize_original_fullwidth_ascii(rows[r['id']]['translation'])),
                              table,overrides=overrides,terminate=True)
        require(len(payload)<=r['capacity'], 'library work title legacy slot overflow')
        plain.extend(payload+bytes(r['capacity']-len(payload)))
    old_pool = current[c['pool_start']:c['pool_end']]
    accepted = {sha(native[c['pool_start']:c['pool_end']]),sha(plain),sha(pool),*c.get('accepted_plain_pool_sha256',[])}
    require(sha(old_pool) in accepted, 'library work title current pool preimage drift')
    output = bytearray(current)
    output[c['pool_start']:c['pool_end']] = pool
    allowed = set(range(c['pool_start'],c['pool_end']))
    name=c['compact_list_name'];at=name['offset'];capacity=name['capacity']
    want=encode_text(compact_library_list_name(name['translation']),table,overrides=overrides,terminate=True)
    plain=encode_text(name['translation'],table,overrides=overrides,terminate=True)
    require(len(want)<=capacity,'library compact list name overflow')
    replacement=want+bytes(capacity-len(want))
    require(current[at:at+capacity] in (native[at:at+capacity],plain+bytes(capacity-len(plain)),replacement),
            'library compact list name current preimage drift')
    output[at:at+capacity]=replacement;allowed.update(range(at,at+capacity))
    for site in name['pointer_sites']:
        require(struct.unpack_from('<I',current,site)[0]==c['base']+at,'library compact list name current pointer drift')
    expected_sites = {}
    for r in targets:
        for site in r['pointer_sites']:
            require(struct.unpack_from('<I',current,site)[0] in
                    (c['base']+r['source_offset'],c['base']+r['offset']),
                    'library work title current pointer drift')
            struct.pack_into('<I',output,site,c['base']+r['offset'])
            allowed.update(range(site,site+4));expected_sites[site]=r
    # Reject references outside the locked pointer words, including interior refs.
    for site in range(0,len(current)-3,4):
        pointer = struct.unpack_from('<I',current,site)[0]-c['base']
        if c['pool_start']<=pointer<c['pool_end']:
            require(site in expected_sites, 'library work title unowned current reference')
    require(all(a==b or i in allowed for i,(a,b) in enumerate(zip(current,output))),
            'library work title write escaped ownership')
    result=dict(entry_count=22,write_entry_count=sum(old_pool[r['offset']-c['pool_start']:r['offset']-c['pool_start']+r['encoded_size']] != pool[r['offset']-c['pool_start']:r['offset']-c['pool_start']+r['encoded_size']] for r in targets),
                titles=targets,pool_start=c['pool_start'],pool_end=c['pool_end'],pool_used=used,
                minimum_output_headroom=len(pool)-used,changed_byte_count=sum(a!=b for a,b in zip(current,output)),
                canonical_title_corpus_reused=True,source_preimages_sha256_exact=True,
                pool_bounds_preserved=True,pointer_targets_reread_exact=True,pointer_count=55,
                zero_padding_preserved=True,reread_exact=True,non_owned_bytes_preserved=True)
    return bytes(output),result


def verify_work_title_pool(data, native, readback, *, edition='original',canonical=None):
    """Independent semantic reread of every title, pointer and pool-tail byte."""
    c, rows = inputs(edition,canonical)
    validate_source(native,c,rows)
    require(len(data)==c['decoded_size'], 'library work title final decoded size drift')
    at=c['pool_start'];titles=[]
    for r in c['entries']:
        expected=two_byte_visible_spaces(library_typography(rows[r['id']]['translation'],'PRDC'))
        actual=decode_text(data,at,readback,end=c['pool_end'])
        require(actual.text==expected and actual.terminator=='nul','library work title final text mismatch: '+r['id'])
        for site in r['pointer_sites']:
            require(struct.unpack_from('<I',data,site)[0]==c['base']+at,
                    'library work title final pointer mismatch: '+r['id'])
        titles.append(dict(id=r['id'],source_offset=r['offset'],offset=at,stored_translation=actual.text,pointer_sites=r['pointer_sites']))
        at+=actual.consumed
        if at%2:
            require(data[at]==0,'library work title final alignment mismatch');at+=1
    require(not any(data[at:c['pool_end']]),'library work title final padding mismatch')
    list_name=list_name_binding(data,c,readback)
    return dict(compact_list_name=list_name,entry_count=22,pointer_count=55,titles=titles,pool_start=c['pool_start'],pool_end=c['pool_end'],
                minimum_output_headroom=c['pool_end']-at,canonical_title_corpus_reused=True,
                source_preimages_sha256_exact=True,pool_bounds_preserved=True,zero_padding_preserved=True,
                readback_exact=True)
