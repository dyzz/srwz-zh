"""Replace complete inherited SP world-map title bitmaps with frozen Chinese pixels.

Sparse byte-run migration leaves Japanese strokes wherever a translated pixel
should become zero. Own the full 512x32 title, preserving palettes, the English
subtitle, terrain records and every byte outside each locked title range.
"""
from pathlib import Path
import base64
import hashlib
import json
import zlib

from srwz.codec import decode_production, reencode_changed_suffix
from special_disc.writeback.install_font import sp_offsets

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT/'config/assets/special-disc/world-map-title-bindings.json'
MEMBER = 'MAP/MAPMODEL.BIN'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def inputs():
    config = json.loads(CONTRACT.read_text())
    require(config['schema_version'] == 1 and config['member'] == MEMBER and
            (config['width'], config['height'], config['raw_size']) == (512, 32, 8192),
            'world-map title contract geometry drift')
    raw = (ROOT/config['snapshot']['path']).read_bytes()
    require(sha(raw) == config['snapshot']['sha256'], 'world-map snapshot drift')
    snapshot = {r['id']:r for r in json.loads(raw)['entries']}
    require([r['chunk'] for r in config['bindings']] ==
            [102, 111, 118, 119, 138, 139, 140, 160, 163, 193],
            'inherited SP world-map title coverage drift')
    for row in config['bindings']:
        frozen = snapshot[row['snapshot_id']]
        for key in ('translation', 'source_raw_sha256', 'output_raw_sha256'):
            require(frozen[key] == row[key], f'world-map binding drift: {key}')
        pixels = zlib.decompress(base64.b64decode(frozen['output_raw_zlib_base64']))
        require(len(pixels) == config['raw_size'] and sha(pixels) == row['output_raw_sha256'],
                'world-map frozen pixels drift')
        row['pixels'] = pixels
    return config


def replace_bitmap(data, row):
    start, pixels = row['offset'], row['pixels']
    end = start + len(pixels)
    require(0 <= start < end <= len(data), 'world-map title range leaves chunk')
    require(sha(data[start:end]) in {row['source_raw_sha256'],
            row['previous_raw_sha256'], row['output_raw_sha256']},
            f"world-map title preimage drift: chunk {row['chunk']}")
    return data[:start] + pixels + data[end:]


def verify_world_map_titles(archive, exe):
    config = inputs()
    offsets = sp_offsets(exe, config['table_offset'], len(archive))
    titles = []
    for row in config['bindings']:
        i, at = row['chunk'], row['offset']
        data = decode_production(archive[offsets[i]:offsets[i+1]]).output
        require(data[at:at+8192] == row['pixels'], f'world-map title pixel mismatch: {i}')
        titles.append({k:row[k] for k in ('chunk', 'translation', 'output_raw_sha256')})
    return dict(count=len(titles), titles=titles, contract_sha256=sha(CONTRACT.read_bytes()),
                snapshot=config['snapshot'], runtime='pending')


def apply_world_map_titles(archive, exe):
    config = inputs()
    offsets = sp_offsets(exe, config['table_offset'], len(archive))
    output = bytearray(archive)
    for row in config['bindings']:
        i = row['chunk']; a, b = offsets[i:i+2]
        stored = archive[a:b]
        decoded = decode_production(stored)
        rebuilt = replace_bitmap(decoded.output, row)
        if rebuilt == decoded.output:
            continue
        packed = reencode_changed_suffix(stored, rebuilt, strategy='rust-fit',
                    max_output_size=b-a, original_result=decoded)
        require(decode_production(packed).output == rebuilt, 'world-map codec readback failed')
        output[a:b] = packed + bytes(b-a-len(packed))
    require(len(output) == len(archive), 'world-map archive size changed')
    result = bytes(output)
    return result, verify_world_map_titles(result, exe)
