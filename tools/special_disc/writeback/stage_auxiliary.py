"""Typed SP name slots and scalar words excluded from pointer relocation.

No raw value is taken as proof of pointer ownership. Adjacent native records or
validated formation owner records establish name capacity; scalar exceptions
also lock the executable consumer and the complete local map-script record.
"""
import hashlib
import json
from srwz.text import decode_text, encode_text, normalize_original_fullwidth_ascii


def formation_groups(data, table, index, base):
    from squad_names import locked_stage_groups
    return locked_stage_groups(data, table, index)


def scalar_sites(data, index, root, exe):
    contract = json.loads((root/'config/products/special-disc/stage-scalar-contracts.json').read_text())
    if hashlib.sha256(exe).hexdigest() != contract['exe_sha256']:
        raise ValueError('scalar consumer executable drift')
    for span in contract['consumer_spans']:
        if exe[span['offset']:span['offset']+len(bytes.fromhex(span['hex']))].hex() != span['hex']:
            raise ValueError('scalar consumer instruction drift')
    sites=[]
    for row in contract['records']:
        if row['chunk'] != index:continue
        at=row['record_offset'];expected=bytes.fromhex(row['record_hex'])
        if data[at:at+len(expected)] != expected:raise ValueError('scalar record preimage drift')
        sites.append(at+4)
    return sites


def write_formations(data, groups, index, bindings, table, overrides, readback, base):
    output=bytearray(data);regions=[];rows=[]
    prefix=f"sd/{'challenge' if 39<=index<=56 else 'story'}/{index:03d}/formation/"
    from squad_names import CORPUS_PATH
    by_source = {}
    for group in groups:
        for cell in group.cells:
            by_source.setdefault(cell.source_text, {})[cell.offset] = (group, cell)
    for source_text, matches in by_source.items():
        at = min(matches)
        target = prefix + f"{at:05X}"
        direct = [(key, value) for key, value in bindings.direct.items()
                  if key.startswith(prefix) and value['source_text'] == source_text]
        if direct:
            if len(direct) != 1 or int(direct[0][0].rsplit('/', 1)[1], 16) not in matches:
                raise ValueError(f'{target}: formation ownership/source drift')
            target, source = direct[0]
            row = bindings.resolve(target, 'formation_name', source_text)
            if row['translation'] != bindings.squad_names[source_text]['translation']:
                raise ValueError('SP reviewed formation translation conflict')
        else:
            source = bindings.squad_names[source_text]
            row = dict(target=target, source_text_sha256=source['source_text_sha256'],
                       translation=source['translation'], route='locked_squad_source',
                       corpus=CORPUS_PATH, corpus_id=source['id'], kind='formation_name',
                       editorial_status=source['editorial_status'])
        text=normalize_original_fullwidth_ascii(row['translation'])
        payload=encode_text(text,table,overrides=overrides,terminate=True)
        writes=[]
        for offset,(group,cell) in sorted(matches.items()):
            if len(payload)>group.slot_size:raise ValueError(f'{target}: name exceeds {group.layout} capacity')
            if decode_text(data,offset,table).text!=source_text:raise ValueError('formation preimage drift')
            output[offset:offset+group.slot_size]=payload+bytes(group.slot_size-len(payload))
            if decode_text(bytes(output),offset,readback).text!=text:raise ValueError('formation readback mismatch')
            regions.append((offset,offset+group.slot_size))
            writes.append(dict(offset=offset,layout=group.layout,capacity=group.slot_size,payload=len(payload)))
        row.update(output_text=text,layout='formation_name',writes=writes);rows.append(row)
    return bytes(output),regions,rows
