"""Carry the reviewed shared bazaar heading into SP without replacing its atlas."""
import json
from pathlib import Path

from special_disc.writeback.title_atlas import decode, positions, require, sha
from srwz.tim2 import parse_tim2

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / 'config/assets/special-disc/bazaar-heading.json'


def cell(atlas, config):
    a, b = config['page_start'], config['page_end']
    require(0 <= a < b <= len(atlas), 'SP bazaar page bounds')
    p = parse_tim2(atlas[a:b]).pictures[0]
    s, size = p.offset + p.header_size, p.image_size
    require((p.width, p.height, p.image_type, s, size) ==
            (256, 256, 4, config['image_start'], config['image_size']), 'SP bazaar format drift')
    require(sha(atlas[a:a+s] + atlas[a+s+size:b]) == config['container_sha256'],
            'SP bazaar header/CLUT/trailer drift')
    indices = bytearray(v for byte in atlas[a+s:a+s+size] for v in (byte & 15, byte >> 4))
    pos = positions(config['rect'])
    pixels = decode(config['indices_zlib_base64'])
    require(len(pixels) == len(pos) and max(pixels) <= 15 and sha(pixels) == config['sha256'],
            'SP bazaar frozen indices drift')
    return a+s, indices, pos, pixels


def contract(config=None):
    raw = CONFIG.read_bytes() if config is None else json.dumps(config, sort_keys=True).encode()
    c = json.loads(raw)
    lock = c['shared_render_snapshot']
    require(lock['path'] == 'config/assets/ui-bazaar-atlas-render-snapshot.json' and
            sha((ROOT / lock['path']).read_bytes()) == lock['sha256'], 'SP bazaar shared snapshot drift')
    return c, dict(config_sha256=sha(raw), indices_sha256=c['sha256'],
                   shared_render_snapshot=lock, runtime='pending')


def apply_bazaar_heading(atlas, config=None):
    c, report = contract(config)
    start, indices, pos, pixels = cell(atlas, c)
    require(sha(bytes(indices[i] for i in pos)) in (c['before_sha256'], c['sha256']),
            'SP bazaar pixel preimage drift')
    for i, value in zip(pos, pixels):
        indices[i] = value
    out = bytearray(atlas)
    out[start:start+len(indices)//2] = bytes(indices[i] | indices[i+1] << 4
                                          for i in range(0, len(indices), 2))
    return bytes(out), report


def verify_bazaar_heading(atlas):
    c, report = contract()
    _, indices, pos, pixels = cell(atlas, c)
    require(bytes(indices[i] for i in pos) == pixels, 'SP bazaar final ISO indices drift')
    return report
