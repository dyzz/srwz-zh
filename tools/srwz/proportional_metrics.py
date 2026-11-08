"""Single source for existing-glyph Latin metrics and EE table serialization.

No rasterization or glyph replacement. Heights are panel-specific candidates.
The EE consumer and authoring engine must consume these same generated records.
"""
import hashlib
import json
from pathlib import Path
import math
import unicodedata
from .font import decode_glyph, standard_glyph_index

PROFILES = {
    'story': (14, 13, 12), 'battle': (14, 12, 11),
    'main_flow': (12, 11, 10), 'sp_flow': (12, 11, 10),
    'main_scroll': (24, 13, 12), 'main_scroll_strip': (24, 13, 12),
    'sp_scroll': (25, 13, 12), 'weapon': (12, 10, 9),
    'weapon_main': (14, 10, 9),
    'library_character': (14, 13, 12), 'keyword_list': (14, 13, 12),
    'library_robot': (14, 11, 10), 'library_glossary': (14, 13, 12),
}

CJK_PUNCTUATION='，。、！？：；“”‘’（）《》【】'
CJK_NATIVE={name:((24,12) if name.startswith('main_scroll') else (25,12) if name=='sp_scroll' else (16,9) if name=='weapon' else (16,10) if name in {'main_flow','sp_flow'} else (21,10) if name=='library_robot' else (21,12)) for name in PROFILES}
CJK_NATIVE['battle']=(22,11)
# Term index names use 18x12 cells, distinct from the 21x12 body.
CJK_NATIVE['keyword_list']=(18,12)
# Main-game combat weapon lists are 20x9; SP Battle Viewer uses 16x9.
CJK_NATIVE['weapon_main']=(20,9)

def punctuation_codes(chars='-./'):
    root=Path(__file__).resolve().parents[2]
    manifest=json.loads((root/'manifests/zh-release-font-validation.json').read_text())
    proposal=json.loads((root/manifest['proposal']['path']).read_text())
    codes={row['character']:int(row['code'],16) for row in proposal['assignments']+proposal.get('surface_alias_assignments',[])}
    return {ch:codes[ch] for ch in chars}

def contextual_slots():
    return [(0x8140,304)]+[(code,308+4*i) for i,code in enumerate(punctuation_codes().values())]

def build_registry(font):
    if len(font) != 4480 * 288:
        raise ValueError('Expected complete native 24x24 4bpp font')
    bounds = {}
    for code in range(0x824f, 0x829b):
        try:
            char = unicodedata.normalize('NFKC', code.to_bytes(2, 'big').decode('cp932'))
        except UnicodeError:
            continue
        if len(char) != 1 or not char.isascii() or not char.isalnum():
            continue
        pixels = decode_glyph(font, standard_glyph_index(code))
        points = [(i % 24, i // 24) for i, value in enumerate(pixels) if value >= 4]
        if not points:
            raise ValueError(f'Empty Latin glyph {code:04x}')
        bounds[char] = dict(code=code, x0=min(x for x,y in points),
                            x1=max(x for x,y in points), y0=min(y for x,y in points),
                            y1=max(y for x,y in points))
    for char,code in punctuation_codes().items():
        pixels=decode_glyph(font,standard_glyph_index(code))
        points=[(i%24,i//24) for i,value in enumerate(pixels) if value>=4]
        if not points:raise ValueError(f'Empty punctuation glyph {code:04x}')
        bounds[char]=dict(code=code,x0=min(x for x,y in points),x1=max(x for x,y in points),y0=min(y for x,y in points),y1=max(y for x,y in points))
    cjk_bounds={}
    for char,code in punctuation_codes(CJK_PUNCTUATION).items():
        pixels=decode_glyph(font,standard_glyph_index(code))
        pts=[(i%24,i//24) for i,v in enumerate(pixels) if v>=4]
        if not pts:raise ValueError(f'Empty CJK punctuation {code:04x}')
        cjk_bounds[char]=dict(code=code,x0=min(x for x,y in pts),x1=max(x for x,y in pts),y0=min(y for x,y in pts),y1=max(y for x,y in pts))
    profiles = {}
    for name, (width, letter, digit) in PROFILES.items():
        glyphs = {}
        for char, b in bounds.items():
            glyphs[char] = dict(code=b['code'], width=width,
                bearing=max(0, round((b['x0']-1)*width/23)-1),
                advance=max(4, math.ceil((b['x1']-b['x0']+1)*width/23)+2),
                height=digit if char.isdigit() else letter,
                yOffset=CJK_NATIVE[name][1]-letter,
                baselineResidual16=round(16*((CJK_NATIVE[name][1]*21-(digit*21 if char.isdigit() else letter*20))/23-(CJK_NATIVE[name][1]-letter))))
        profiles[name] = dict(glyphs={ch:m for ch,m in glyphs.items() if ch.isalnum()}, punctuation={ch:m for ch,m in glyphs.items() if not ch.isalnum()}, space=dict(code=0x8140,
            width=width, bearing=0, advance=max(4, round(width/3)), height=digit))
        native_width,native_height=CJK_NATIVE[name];compact={}
        for char,b in cjk_bounds.items():
            ink_width=math.ceil((b['x1']-b['x0']+1)*native_width/24)
            advance=max(math.ceil(native_width*0.75),ink_width+4)
            desired=(advance-ink_width-2 if char in '“‘（《【' else (advance-ink_width)//2 if char in '：' else 2)
            bearing=max(0,round(b['x0']*native_width/24)-desired)
            compact[char]=dict(code=b['code'],width=native_width,height=native_height,bearing=bearing,advance=advance)
        profiles[name]['cjkPunctuation']=compact
    return dict(schemaVersion=6,cjkBounds=cjk_bounds, fontSha256=hashlib.sha256(font).hexdigest(),
                inkThreshold=4, bounds=bounds, profiles=profiles)

def runtime_table(profile, *, include_residuals=False):
    """62 enabled alnums in 76 slots, followed by contextual space slot.

    Bytes per record: bearing, advance, height, signed-y-offset/enable.
    Bit 0 enables the record; bits 1..7 hold a signed seven-bit Y offset. The draw consumer
    supplies profile width; a space is selected only between enabled alnums.
    """
    def flags(metric):
        y=metric.get('yOffset',0)
        if not -64<=y<=63:raise ValueError('Y offset outside signed seven-bit range')
        return ((y&127)<<1)|1
    table = bytearray(80 * 4)
    for metric in profile['glyphs'].values():
        at = (metric['code'] - 0x824f) * 4
        table[at:at+4] = bytes((metric['bearing'], metric['advance'], metric['height'], flags(metric)))
    m = profile['space']
    table[304:308] = bytes((m['bearing'], m['advance'], m['height'], flags(m)))
    for i,metric in enumerate(profile['punctuation'].values()):
        table[308+i*4:312+i*4]=bytes((metric['bearing'],metric['advance'],metric['height'],flags(metric)))
    if include_residuals:
        residuals=bytearray(80)
        for m in profile['glyphs'].values():residuals[m['code']-0x824f]=m.get('baselineResidual16',0)&255
        for i,m in enumerate(profile['punctuation'].values()):residuals[77+i]=m.get('baselineResidual16',0)&255
        table.extend(residuals)
    return bytes(table)
