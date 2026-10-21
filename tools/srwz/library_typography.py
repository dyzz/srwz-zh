"""Surface-specific closed scopes for encyclopedia Latin, digits and symbols.

Stock glyphs and logical text remain unchanged. Metrics are those of the native
panels, including their height; a width-only restore inherits the wrong height.
"""
from __future__ import annotations
import re
from .text import CONTROL_NOTATION, normalize_original_fullwidth_ascii
from .library_height_restore import ENCODED_HEIGHT_10
from .library_optical_metrics import OPTICAL_HEIGHTS

BODY_TAGS = frozenset({'DSCR', 'DSC2'})
NAME_TAGS = frozenset({'RBTN', 'CHFN'})
METADATA_TAGS = frozenset({'PRDC', 'ACTR', 'CHNN'})
PARAMETER_TAGS = frozenset({'HEIT', 'WEIT'})
BODY_HEIGHTS = {'character':12,'robot':10,'glossary':12}
# Native PRDC is 21/21/10, distinct from both the 21px prose and name panel.
SURFACES = {**{tag: (21, 21, 12) for tag in BODY_TAGS},
            **{tag: (18, 18, 10) for tag in NAME_TAGS},
            **{tag: (21, 21, 10) for tag in METADATA_TAGS},
            **{tag: (12, 12, 10) for tag in PARAMETER_TAGS}}
SYMBOLS = 'Σσ∀αβγδΩⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ()（）[]［］'
ALPHABET = r'A-Za-z0-9Ａ-Ｚａ-ｚ０-９Σσ∀αβγδΩⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ()（）\[\]［］'
RUN = re.compile(rf'[{ALPHABET}]+(?:[ .,:：．_\'/／＋+％%~～〜×±＝=　－−·-]+[{ALPHABET}]+)*[%％]?')
OWNED = re.compile(r'<width:(?:0E|0C)><space:(?:0A|0C)>(?:<height:[0-9A-Fa-f]{2}>)?'
                   rf'((?:[{ALPHABET} .,:：．_\'/／＋+％%~～〜×±＝=　－−·《》-]|<height:[0-9A-Fa-f]{{2}}>)+)'
                   r'(?:<width:[0-9A-Fa-f]{2}><space:[0-9A-Fa-f]{2}>'
                   r'|<space:[0-9A-Fa-f]{2}><width:[0-9A-Fa-f]{2}>)'
                   r'(?:<height:[0-9A-Fa-f]{2}>)?')
DOME_OWNED = re.compile(r'<width:10><space:0E>(?:<height:0A>)?D\.O\.M\.E\.G-Bit'
                        r'<width:12><space:12>(?:<height:0A>)?')
DIMENSION = re.compile(r'<(width|space|height):([0-9A-Fa-f]{2})>\Z')
BOUNDARY = re.compile(r'＜ｔｍ＞.*?＜／ｔｍ＞|<tm>.*?</tm>|<<[^>]+>>|'
                      + CONTROL_NOTATION.pattern + r'|\\[nrt]|\\u[0-9A-Fa-f]{4}', re.S)


def normalize_body_controls(text: str) -> str:
    """Migrate generated 22px horizontal baselines/restores to native 21px.

    The native row initializer supplies the baseline height/vertical advance.
    Body height restoration is domain-specific; raw height10 is encoded as8A.
    """
    return text.replace('<width:16><space:16>', '<width:15><space:15>').replace(
        '<space:16><width:16>', '<space:15><width:15>')


def library_typography(text: str, tag: str, *, domain: str | None = None) -> str:
    """Compile one supported field, preserving templates and native controls."""
    if tag not in SURFACES:
        return text
    folded = normalize_original_fullwidth_ascii(text)
    if tag in BODY_TAGS:
        folded = normalize_body_controls(folded)
        folded = re.sub(r'<height:0[Aa]>', '<height:8A>', folded)
    logical = OWNED.sub(lambda match: re.sub(r'<height:[0-9A-Fa-f]{2}>', '', match[1]),
                        DOME_OWNED.sub('D.O.M.E.G-Bit', folded))
    state = dict(zip(('width', 'space', 'height'), SURFACES[tag]))
    if tag in BODY_TAGS and domain is not None:
        state['height'] = BODY_HEIGHTS[domain]
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
            # Optical operands change record Y, not the text pen or line pitch.
            # Keep one closed width/advance scope so mixed identifiers remain
            # atomic during layout, but give digits their own visible height.
            body_content = None
            if tag in BODY_TAGS:
                # Letter and digit ink heights are independent of Chinese.
                # For the native character height12, use the requested smaller
                # 12/11 pair; the optical letter record still moves up1.
                # Robot height10 retains its calibrated 11/10 pair.
                letter_height = max(1, (state['height'] * 13 + 6) // 12)
                digit_height = state['height']
                if state['height'] == 12:
                    letter_height, digit_height = 12, 11
                default_optical = bool(re.search(r'[A-Za-z]', run))
                default_height = letter_height if default_optical else digit_height
                active = None
                parts = []
                previous = default_height
                previous_optical = default_optical
                for character in run:
                    if character.isascii() and character.isalpha():
                        actual_height = letter_height
                        optical = True
                    elif character.isascii() and character.isdigit():
                        actual_height = digit_height
                        optical = False
                    elif character in '()（）[]［］' or character in 'Σσ∀αβγδΩⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ':
                        actual_height = default_height
                        optical = default_optical
                    else:
                        actual_height = previous
                        optical = previous_optical
                    operand = (ENCODED_HEIGHT_10 if actual_height == 10 else
                               actual_height | 0x80 if optical and actual_height in OPTICAL_HEIGHTS.values() else actual_height)
                    if operand != active:
                        parts.append(f'<height:{operand:02X}>')
                        active = operand
                    parts.append(character)
                    previous = actual_height
                    previous_optical = optical
                body_content = ''.join(parts)
            opening_height = f'<height:{height:02X}>'
            restored_height = ENCODED_HEIGHT_10 if tag in BODY_TAGS and state['height'] == 10 else state['height']
            closing_height = f'<height:{restored_height:02X}>'
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
            return f'<width:{glyph_width:02X}><space:{advance:02X}>' + (body_content if body_content is not None else opening_height + run) + restore + closing_height
        return RUN.sub(replace, chunk)

    for token in BOUNDARY.finditer(logical):
        output.append(plain(logical[cursor:token.start()]))
        output.append(token.group())
        dimension = DIMENSION.fullmatch(token.group())
        if dimension:
            value = int(dimension[2], 16)
            state[dimension[1]] = value & 0x7F if dimension[1]=='height' and (value==ENCODED_HEIGHT_10 or value in OPTICAL_HEIGHTS) else value
        cursor = token.end()
    output.append(plain(logical[cursor:]))
    result = ''.join(output)
    if CONTROL_NOTATION.sub('', result) != CONTROL_NOTATION.sub('', folded):
        raise ValueError('encyclopedia typography changed visible text')
    return result
