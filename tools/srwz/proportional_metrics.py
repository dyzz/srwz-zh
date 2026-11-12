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

# Proportional scenes. Latin letters, digits and identifier punctuation come from the
# HarmonyOS Latin bank (srwz.latin_bank) and are drawn in the scene's own hanzi cell:
# same width and height as the hanzi, no lift and no baseline residual, because the
# bank shares the hanzi rasterizer and baseline (user decision 2026-11-12).
SCENES = ('story', 'sp_story_map', 'battle', 'main_flow', 'sp_flow', 'main_scroll',
          'main_scroll_strip', 'sp_scroll', 'weapon', 'weapon_main', 'library_character',
          'keyword_list', 'library_robot', 'library_glossary')

CJK_PUNCTUATION='，。、！？：；“”‘’（）《》【】'
CJK_NATIVE={name:((24,12) if name.startswith('main_scroll') else (25,12) if name=='sp_scroll' else (16,9) if name=='weapon' else (16,10) if name in {'main_flow','sp_flow'} else (21,10) if name=='library_robot' else (21,12)) for name in SCENES}
CJK_NATIVE['battle']=(22,11)
CJK_NATIVE['sp_story_map']=(20,11)
# Term index names use 18x12 cells, distinct from the 21x12 body.
CJK_NATIVE['keyword_list']=(18,12)
# Main-game combat weapon lists are 20x9; SP Battle Viewer uses 16x9.
CJK_NATIVE['weapon_main']=(20,9)
# (Latin cell width, letter height, digit height): the hanzi cell itself.
PROFILES={name:(CJK_NATIVE[name][0],CJK_NATIVE[name][1],CJK_NATIVE[name][1]) for name in SCENES}
# Latin bearing/advance are shared by scenes of similar cell width, so the runtime carries
# three metric tables instead of one per width (user decision 2026-11-12; the SP code cave
# cannot hold more). Each class is computed at its reference width; a glyph drawn in a
# cell one or two pixels wider or narrower is at most a pixel looser or tighter.
METRIC_CLASS_WIDTH={'body':21,'compact':17,'scroll':24}
METRIC_CLASS={name:('scroll' if CJK_NATIVE[name][0]>=24 else 'compact' if CJK_NATIVE[name][0]<=18 else 'body') for name in SCENES}
# Punctuation that keeps its native full-width advance in a scene. Battle subtitles open
# every line with “ and indent the continuation row by one full-width space, so a
# compact opening quote would leave row 2 five pixels to the right of row 1.
CJK_FULL_WIDTH={'battle':'“'}
# Scenes whose continuation rows indent by continuation_indent.CODE instead of a
# full-width space. Story dialogue shares its 21px metrics with the library scenes, and
# the native measure path picks a table by width alone, so all of them carry the record.
CONTINUATION_INDENT_WIDTH=21

# 76 native alphanumeric slots, one contextual space and four punctuation slots.
# Keep slash last: the selector uses that record for spaced A / B expressions.
METRIC_SLOTS = 81
METRIC_BYTES = METRIC_SLOTS * 4

def punctuation_codes(chars="-.'/"):
    root=Path(__file__).resolve().parents[2]
    manifest=json.loads((root/'manifests/zh-release-font-validation.json').read_text())
    proposal=json.loads((root/manifest['proposal']['path']).read_text())
    codes={row['character']:int(row['code'],16) for row in proposal['assignments']+proposal.get('surface_alias_assignments',[])}
    return {ch:codes[ch] for ch in chars}

def punctuation_glyph_index(code):
    """Assignments include extended codes such as apostrophe E6C3."""
    root=Path(__file__).resolve().parents[2]
    manifest=json.loads((root/'manifests/zh-release-font-validation.json').read_text())
    proposal=json.loads((root/manifest['proposal']['path']).read_text())
    return next(row['glyph_index'] for row in proposal['assignments']+proposal.get('surface_alias_assignments',[]) if int(row['code'],16)==code)

def space_codes():
    """Every code a word space is stored as: stock 0x8140 and the release-font ASCII space.

    Surfaces that convert spaces at the storage boundary write 0x8140; encoders that
    use every surface-safe alias (story, library, battle) write the ASCII space's alias.
    Both draw the contextual space record between alnums. The primary release code is
    never emitted by those encoders and is left out to fit the SP code cave.
    """
    root=Path(__file__).resolve().parents[2]
    manifest=json.loads((root/'manifests/zh-release-font-validation.json').read_text())
    proposal=json.loads((root/manifest['proposal']['path']).read_text())
    alias=[int(row['code'],16) for row in proposal.get('surface_alias_assignments',[]) if row['character']==' ']
    if len(alias)!=1:raise ValueError('Release font must have exactly one ASCII space alias')
    return [0x8140,*alias]

def contextual_slots():
    """Space codes share slot 304; identifier punctuation follows, slash last."""
    return [(code,304) for code in space_codes()]+[(code,308+4*i) for i,code in enumerate(punctuation_codes().values())]

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
        pixels=decode_glyph(font,punctuation_glyph_index(code))
        points=[(i%24,i//24) for i,value in enumerate(pixels) if value>=4]
        if not points:raise ValueError(f'Empty punctuation glyph {code:04x}')
        bounds[char]=dict(code=code,x0=min(x for x,y in points),x1=max(x for x,y in points),y0=min(y for x,y in points),y1=max(y for x,y in points))
    cjk_bounds={}
    for char,code in punctuation_codes(CJK_PUNCTUATION).items():
        pixels=decode_glyph(font,punctuation_glyph_index(code))
        pts=[(i%24,i//24) for i,v in enumerate(pixels) if v>=4]
        if not pts:raise ValueError(f'Empty CJK punctuation {code:04x}')
        cjk_bounds[char]=dict(code=code,x0=min(x for x,y in pts),x1=max(x for x,y in pts),y0=min(y for x,y in pts),y1=max(y for x,y in pts))
    return dict(schemaVersion=7,cjkBounds=cjk_bounds, fontSha256=hashlib.sha256(font).hexdigest(),
                inkThreshold=4, bounds=bounds, profiles=build_profiles(bounds,cjk_bounds))

def build_profiles(bounds,cjk_bounds):
    """Scene profiles: Latin metrics from the glyph bank, compact CJK punctuation from ink bounds.

    ``bounds`` still names the Latin codes (and keeps the stock ink boxes on record);
    their bearing and advance now come from the bank font's own advance widths.
    """
    from . import latin_bank
    root=Path(__file__).resolve().parents[2]
    bank=latin_bank.load(root)
    profiles = {}
    for name, (width, letter, digit) in PROFILES.items():
        glyphs = {}
        for char, b in bounds.items():
            bearing,advance=latin_bank.advance_px(bank,char,METRIC_CLASS_WIDTH[METRIC_CLASS[name]])
            # advanceBox: the ink lies inside [pen, pen+advance); the rest of the hanzi-wide
            # cell is transparent, so a row's extent ends at the advance, not at the cell edge.
            glyphs[char] = dict(code=b['code'], width=width, bearing=bearing, advance=advance,
                height=digit if char.isdigit() else letter, yOffset=0, baselineResidual16=0, advanceBox=True)
        profiles[name] = dict(glyphs={ch:m for ch,m in glyphs.items() if ch.isalnum()}, punctuation={ch:m for ch,m in glyphs.items() if not ch.isalnum()}, space=dict(code=0x8140,
            width=width, bearing=0, advance=latin_bank.space_advance(bank,METRIC_CLASS_WIDTH[METRIC_CLASS[name]]), height=digit))
        native_width,native_height=CJK_NATIVE[name];compact={}
        for char,b in cjk_bounds.items():
            if char in CJK_FULL_WIDTH.get(name,''):continue
            ink_width=math.ceil((b['x1']-b['x0']+1)*native_width/24)
            advance=max(math.ceil(native_width*0.75),ink_width+4)
            desired=(advance-ink_width-2 if char in '“‘（《【' else (advance-ink_width)//2 if char in '：' else 2)
            bearing=max(0,round(b['x0']*native_width/24)-desired)
            compact[char]=dict(code=b['code'],width=native_width,height=native_height,bearing=bearing,advance=advance)
        profiles[name]['cjkPunctuation']=compact
        if (native_width==CONTINUATION_INDENT_WIDTH or name=='sp_story_map') and '“' in compact:
            from .continuation_indent import CODE,OPENERS
            if {compact[char]['advance'] for char in OPENERS}!={compact['“']['advance']}:
                raise ValueError('Compact opening punctuation no longer shares one advance')
            profiles[name]['continuationIndent']=dict(code=CODE,width=native_width,height=native_height,bearing=0,advance=compact['“']['advance'],openers=OPENERS)
    return profiles

def compact_runtime_table(profile):
    """Two bytes per slot (bearing, advance) in the 81-slot layout; advance 0 marks a gap."""
    table=bytearray(METRIC_SLOTS*2)
    for metric in profile['glyphs'].values():
        at=(metric['code']-0x824f)*2;table[at:at+2]=bytes((metric['bearing'],metric['advance']))
    table[152:154]=bytes((profile['space']['bearing'],profile['space']['advance']))
    for i,metric in enumerate(profile['punctuation'].values()):
        table[154+i*2:156+i*2]=bytes((metric['bearing'],metric['advance']))
    if any(table[at+1]==0 for at in (152,154,156,158,160)):raise ValueError('Enabled metric with zero advance')
    return bytes(table)

def runtime_table(profile, *, include_residuals=False):
    """62 enabled alnums in 76 slots, then space and punctuation records.

    Bytes per record: bearing, advance, height, signed-y-offset/enable.
    Bit 0 enables the record; bits 1..7 hold a signed seven-bit Y offset. The draw consumer
    supplies profile width; a space is selected only between enabled alnums.
    """
    def flags(metric):
        y=metric.get('yOffset',0)
        if not -64<=y<=63:raise ValueError('Y offset outside signed seven-bit range')
        return ((y&127)<<1)|1
    table = bytearray(METRIC_BYTES)
    for metric in profile['glyphs'].values():
        at = (metric['code'] - 0x824f) * 4
        table[at:at+4] = bytes((metric['bearing'], metric['advance'], metric['height'], flags(metric)))
    m = profile['space']
    table[304:308] = bytes((m['bearing'], m['advance'], m['height'], flags(m)))
    for i,metric in enumerate(profile['punctuation'].values()):
        table[308+i*4:312+i*4]=bytes((metric['bearing'],metric['advance'],metric['height'],flags(metric)))
    if include_residuals:
        residuals=bytearray(METRIC_SLOTS)
        for m in profile['glyphs'].values():residuals[m['code']-0x824f]=m.get('baselineResidual16',0)&255
        for i,m in enumerate(profile['punctuation'].values()):residuals[77+i]=m.get('baselineResidual16',0)&255
        table.extend(residuals)
    return bytes(table)
