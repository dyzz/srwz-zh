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
    """Refine only the Chinese title in SP HSFC chunk 1, within its budget."""
    import struct
    from .codec import decode_production, reencode_changed_suffix
    raw = (root/'config/assets/special-disc/chart-title-clarity.json').read_bytes()
    c = json.loads(raw)
    a,b = struct.unpack_from('<II',executable,c['table_offset']+c['chunk']*4)
    if not 0 <= a < b <= len(archive):
        raise ValueError('clarity chart allocation drift')
    old = decode_production(archive[a:b]); data = bytearray(old.output)
    x,y,w,h=c['rect'];start=c['decoded_offset'];width=c['width']
    rs,re=c['record_offset'],c['record_offset']+c['record_size']
    if sha(data[rs:start]+data[start+512*512:re]) != c['container_sha256']:
        raise ValueError('clarity chart palette/header drift')
    pos=[start+yy*width+xx for yy in range(y,y+h) for xx in range(x,x+w)]
    before,after=[zlib.decompress(base64.b64decode(c[k+'_zlib_base64'],validate=True)) for k in ('before','after')]
    if len(before)!=w*h or len(after)!=w*h or sha(before)!=c['before_sha256'] or sha(after)!=c['after_sha256']:
        raise ValueError('clarity chart frozen data drift')
    current=bytes(data[i] for i in pos)
    if current not in (before,after) or (verify and current!=after):
        raise ValueError('clarity chart preimage drift')
    report=dict(config_sha256=sha(raw),member=c['member'],chunk=c['chunk'],rect=c['rect'])
    if current==after:return archive,report
    for i,v in zip(pos,after):data[i]=v
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
