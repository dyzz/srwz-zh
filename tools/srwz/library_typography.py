"""Surface-specific closed scopes for encyclopedia Latin, digits and symbols.

Stock glyphs and logical text remain unchanged. Metrics are those of the native
panels, including their height; a width-only restore inherits the wrong height.
"""
from __future__ import annotations
import re
from .text import CONTROL_NOTATION, normalize_original_fullwidth_ascii

BODY_TAGS = frozenset({'DSCR', 'DSC2'})
NAME_TAGS = frozenset({'RBTN', 'CHFN'})
METADATA_TAGS = frozenset({'PRDC', 'ACTR', 'CHNN'})
PARAMETER_TAGS = frozenset({'HEIT', 'WEIT'})
# Native PRDC is 21/21/10, distinct from both the 22px prose and name panel.
SURFACES = {**{tag: (22, 22, 11) for tag in BODY_TAGS},
            **{tag: (18, 18, 10) for tag in NAME_TAGS},
            **{tag: (21, 21, 10) for tag in METADATA_TAGS},
            **{tag: (12, 12, 10) for tag in PARAMETER_TAGS}}
SYMBOLS = 'Σσ∀αβγδΩⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ()（）[]［］'
ALPHABET = r'A-Za-z0-9Ａ-Ｚａ-ｚ０-９Σσ∀αβγδΩⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ()（）\[\]［］'
RUN = re.compile(rf'[{ALPHABET}]+(?:[ .,:：．_\'/／＋+％%~～〜×±＝=　－−·-]+[{ALPHABET}]+)*[%％]?')
OWNED = re.compile(r'<width:(?:0E|0C)><space:(?:0A|0C)>(?:<height:[0-9A-Fa-f]{2}>)?'
                   rf'([{ALPHABET} .,:：．_\'/／＋+％%~～〜×±＝=　－−·《》-]+)'
                   r'(?:<width:[0-9A-Fa-f]{2}><space:[0-9A-Fa-f]{2}>'
                   r'|<space:[0-9A-Fa-f]{2}><width:[0-9A-Fa-f]{2}>)'
                   r'(?:<height:[0-9A-Fa-f]{2}>)?')
DOME_OWNED = re.compile(r'<width:10><space:0E>(?:<height:0A>)?D\.O\.M\.E\.G-Bit'
                        r'<width:12><space:12>(?:<height:0A>)?')
DIMENSION = re.compile(r'<(width|space|height):([0-9A-Fa-f]{2})>\Z')
BOUNDARY = re.compile(r'＜ｔｍ＞.*?＜／ｔｍ＞|<tm>.*?</tm>|<<[^>]+>>|'
                      + CONTROL_NOTATION.pattern + r'|\\[nrt]|\\u[0-9A-Fa-f]{4}', re.S)


def library_typography(text: str, tag: str) -> str:
    """Compile one supported field, preserving templates and native controls."""
    if tag not in SURFACES:
        return text
    folded = normalize_original_fullwidth_ascii(text)
    logical = OWNED.sub(r'\1', DOME_OWNED.sub('D.O.M.E.G-Bit', folded))
    state = dict(zip(('width', 'space', 'height'), SURFACES[tag]))
    output, cursor = [], 0

    def plain(chunk):
        def replace(match):
            run = match.group()
            # The division glyph requires its native width for legibility.
            if '÷' in run:
                return run
            height = max(1, state['height'] - (1 if re.search(r'[0-9]', run) else 0))
            restore = (f"<space:{state['space']:02X}><width:{state['width']:02X}>"
                       if run.endswith(('%', '％')) else
                       f"<width:{state['width']:02X}><space:{state['space']:02X}>")
            # The encyclopedia prose splitter treats byte 0x0A as a line
            # break even inside a height parameter. Body scopes therefore
            # change horizontal metrics only; the stock digit rasters remain.
            opening_height = '' if tag in BODY_TAGS else f'<height:{height:02X}>'
            closing_height = '' if tag in BODY_TAGS else f"<height:{state['height']:02X}>"
            glyph_width = 12 if tag in PARAMETER_TAGS else 14
            advance = 12
            if tag == 'PRDC' and re.search(r'[A-Za-z]', run):
                # The stock Latin ink is narrower than the 14px glyph cell.
                # Work titles need less tracking than names and prose; keep
                # word spaces in this same scope and restore the native panel.
                advance = 10
            if tag in NAME_TAGS and run == 'D.O.M.E.G-Bit':
                # User requested one step more breathing room for this long name.
                glyph_width, advance = 16, 14
            return f'<width:{glyph_width:02X}><space:{advance:02X}>' + opening_height + run + restore + closing_height
        return RUN.sub(replace, chunk)

    for token in BOUNDARY.finditer(logical):
        output.append(plain(logical[cursor:token.start()]))
        output.append(token.group())
        dimension = DIMENSION.fullmatch(token.group())
        if dimension:
            state[dimension[1]] = int(dimension[2], 16)
        cursor = token.end()
    output.append(plain(logical[cursor:]))
    result = ''.join(output)
    if CONTROL_NOTATION.sub('', result) != CONTROL_NOTATION.sub('', folded):
        raise ValueError('encyclopedia typography changed visible text')
    return result
