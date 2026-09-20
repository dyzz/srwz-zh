"""Typed SP name slots and scalar words excluded from pointer relocation.

No raw value is taken as proof of pointer ownership. Adjacent native records or
validated formation owner records establish name capacity; scalar exceptions
also lock the executable consumer and the complete local map-script record.
"""
from pathlib import Path
import hashlib
import json
import struct
from srwz import stage_formations as sf
from srwz.text import decode_text, encode_text, normalize_original_fullwidth_ascii


def formation_groups(data, table, index, base):
    previous = sf.STAGE_BASE_ADDRESS
    sf.STAGE_BASE_ADDRESS = base
    try:
        return (*sf._scan_structural_record_groups(data, table, stage_index=index),
                *sf._scan_structural_formation_groups(data, table, stage_index=index),
                *sf._scan_packed8_groups(data, table, stage_index=index, source_texts=None, owner_data=data))
    finally:
        sf.STAGE_BASE_ADDRESS = previous


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
    for target,source in bindings.direct.items():
        if not target.startswith(prefix):continue
        at=int(target.rsplit('/',1)[1],16)
        matches={cell.offset:(group,cell) for group in groups for cell in group.cells if cell.source_text==source['source_text']}
        if not matches or min(matches)!=at:raise ValueError(f'{target}: formation ownership/source drift')
        row=bindings.resolve(target,'formation_name',source['source_text'])
        text=normalize_original_fullwidth_ascii(row['translation'])
        payload=encode_text(text,table,overrides=overrides,terminate=True)
        writes=[]
        for offset,(group,cell) in sorted(matches.items()):
            if len(payload)>group.slot_size:raise ValueError(f'{target}: name exceeds {group.layout} capacity')
            if decode_text(data,offset,table).text!=source['source_text']:raise ValueError('formation preimage drift')
            output[offset:offset+group.slot_size]=payload+bytes(group.slot_size-len(payload))
            if decode_text(bytes(output),offset,readback).text!=text:raise ValueError('formation readback mismatch')
            regions.append((offset,offset+group.slot_size))
            writes.append(dict(offset=offset,layout=group.layout,capacity=group.slot_size,payload=len(payload)))
        row.update(output_text=text,layout='formation_name',writes=writes);rows.append(row)
    return bytes(output),regions,rows
