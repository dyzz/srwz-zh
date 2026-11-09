"""Bounded indexed text refinements after native menu restoration.

Frozen before/after cells retain both palette layers. Never touch the CLUT,
any index outside the owned cells. Native title restoration separately restores
the original SELECT / FORMATION / SORT polygons and SORT palette indices.
"""
import base64
import hashlib
import json
import zlib
from pathlib import Path
from .tim2 import parse_tim2

CONFIG = 'config/assets/ui-text-clarity.json'

def sha(data):
    return hashlib.sha256(data).hexdigest()

def apply_atlas(atlas, root: Path, edition='original', *, reverse=False, strict=False):
    raw = (root / CONFIG).read_bytes()
    config = json.loads(raw)['profiles']['original' if edition == 'best' else edition]
    if len(atlas) != config['size']:
        raise ValueError('clarity atlas size drift')
    result = bytearray(atlas)
    for cell in config['cells']:
        start = cell['page'] * 33344
        chunk = atlas[start:start + 33344]
        pic = parse_tim2(chunk).pictures[0]
        a = pic.offset + pic.header_size
        if (pic.width,pic.height,pic.image_type,a,pic.image_size) != (256,256,4,64,32768):
            raise ValueError('clarity atlas geometry drift')
        if sha(chunk[:a]+chunk[a+32768:]) != cell['container_sha256']:
            raise ValueError('clarity palette drift')
        x,y,w,h = cell['rect']
        if not (0 <= x < x+w <= 256 and 0 <= y < y+h <= 256):
            raise ValueError('clarity cell bounds')
        before,after = [zlib.decompress(base64.b64decode(cell[k+'_zlib_base64'],validate=True)) for k in ('before','after')]
        if len(before) != w*h or len(after) != w*h or sha(before) != cell['before_sha256'] or sha(after) != cell['after_sha256']:
            raise ValueError('clarity frozen cell drift')
        if not all(any(lo <= v <= hi for v in after) for lo,hi in ((1,7),(8,15))):
            raise ValueError('clarity fill/outline layer missing')
        positions = [yy*256+xx for yy in range(y,y+h) for xx in range(x,x+w)]
        current = bytes((result[start+a+i//2] >> ((i%2)*4)) & 15 for i in positions)
        if current not in (before,after) or (strict and current != after):
            raise ValueError('clarity cell preimage drift: '+cell['id'])
        for i,v in zip(positions,before if reverse else after):
            off=start+a+i//2;shift=(i%2)*4
            result[off]=(result[off] & ~(15<<shift)) | (v<<shift)
    return bytes(result),dict(config_sha256=sha(raw),cells=[c['id'] for c in config['cells']])

def apply_chart(archive, executable, root: Path, *, verify=False):
    """Install the frozen Special Disc and Z chart labels in their stock styles."""
    import struct
    from .codec import decode_production, reencode_changed_suffix
    raw = (root/'config/assets/special-disc/chart-title-clarity.json').read_bytes()
    c = json.loads(raw)
    a,b = struct.unpack_from('<II',executable,c['table_offset']+c['chunk']*4)
    if not 0 <= a < b <= len(archive):
        raise ValueError('clarity chart allocation drift')
    old = decode_production(archive[a:b])
    data = bytearray(old.output)
    records = []
    if c['schema_version'] != 2 or {r['tab'] for r in c['records']} != {'Special Disc', 'Z'}:
        raise ValueError('clarity chart scope drift')
    for r in c['records']:
        x, y, w, h = r['rect']
        start, width = r['decoded_offset'], r['width']
        image_size = r['image_size']
        rs, re = r['record_offset'], r['record_offset'] + r['record_size']
        if (not 0 <= rs < start < start + image_size < re <= len(data)
                or not (0 <= x < x+w <= width and 0 <= y < y+h <= image_size//width)
                or sha(old.output[rs:start] + old.output[start+image_size:re]) != r['container_sha256']):
            raise ValueError('clarity chart region or palette drift')
        after = zlib.decompress(base64.b64decode(r['after_zlib_base64'], validate=True))
        if (len(after) != w*h or sha(after) != r['after_sha256']
                or not {r['native_fill_index'], r['native_outline_index']}.issubset(after)):
            raise ValueError('clarity chart frozen title drift')
        pos = [start+yy*width+xx for yy in range(y,y+h) for xx in range(x,x+w)]
        current = bytes(old.output[i] for i in pos)
        if current != after and (verify or sha(current) not in r['before_sha256']):
            raise ValueError('clarity chart preimage drift')
        for i, v in zip(pos, after):
            data[i] = v
        records.append(dict(tab=r['tab'], rect=r['rect'], sha256=r['after_sha256']))
    report = dict(config_sha256=sha(raw), member=c['member'], chunk=c['chunk'], records=records)
    if data == old.output:
        return archive, report
    packed=reencode_changed_suffix(archive[a:b],bytes(data),strategy='rust-fit',max_output_size=b-a,original_result=old)
    if len(packed)>b-a or decode_production(packed).output!=data:
        raise ValueError('clarity chart roundtrip/budget failure')
    return archive[:a]+packed+bytes(b-a-len(packed))+archive[b:],report

def apply_native_select(drawings, root: Path, edition='original', *, reverse=False, strict=False):
    raw=(root/'config/assets/ui-select-native.json').read_bytes()
    c=json.loads(raw)['profiles']['original' if edition=='best' else edition]
    if len(drawings)!=c['size']:raise ValueError('native SELECT drawings size drift')
    out=bytearray(drawings)
    for p in c['patches']:
        off=p['offset'];before=bytes.fromhex(p['before_hex']);after=bytes.fromhex(p['after_hex'])
        if len(before)!=34 or len(after)!=34 or not 0<=off<=len(out)-34:raise ValueError('native SELECT patch bounds')
        if drawings[off:off+34] not in (before,after,bytes.fromhex(p.get('previous_hex',p['before_hex']))) or (strict and drawings[off:off+34]!=after):raise ValueError('native SELECT preimage drift')
        out[off:off+34]=before if reverse else after
    return bytes(out),dict(config_sha256=sha(raw),patches=len(c['patches']))

def apply_native_title_atlas(atlas, root: Path, edition='original', *, reverse=False, strict=False):
    c=json.loads((root/'config/assets/ui-select-native.json').read_text())['profiles']['original' if edition=='best' else edition]['atlas_cell']
    x,y,w,h=c['rect'];start=c['page']*33344+64
    if not (0 <= x < x+w <= 256 and 0 <= y < y+h <= 256 and 64 <= start <= len(atlas)-32768):
        raise ValueError('native title atlas bounds drift')
    before,after=[zlib.decompress(base64.b64decode(c[k+'_zlib_base64'],validate=True))for k in ('before','after')]
    if len(before)!=w*h or len(after)!=w*h or sha(before)!=c['before_sha256'] or sha(after)!=c['after_sha256'] or any(v>15 for v in before+after):raise ValueError('native title pixels drift')
    pos=[yy*256+xx for yy in range(y,y+h)for xx in range(x,x+w)]
    current=bytes((atlas[start+i//2]>>((i%2)*4))&15 for i in pos)
    if current not in (before,after) or (strict and current!=after):raise ValueError('native SORT preimage drift')
    out=bytearray(atlas)
    for i,v in zip(pos,before if reverse else after):
        a=start+i//2;s=i%2*4;out[a]=(out[a]&~(15<<s))|(v<<s)
    return bytes(out)
