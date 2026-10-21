"""Closed optical-height scopes in the native text parser, three editions.

8A restores height10 without an LF operand. 8B..8E select heights11..14
and shift only the produced glyph record up1. The pen/advance stay native.
Optical Y and explicit-height markers share checked parser-frame bytes SP+58..5B.
Compact digits without explicit height use an automatic H-1 record adjustment.
Repacking the original control span and reusing its reserved tail avoids new
heap/BSS/ELF segments. Every code/data preimage is checked as one patch owner.
"""
from __future__ import annotations
import hashlib
import struct
from .compact_digit_metrics import regions as digit_regions
from .library_body_metrics import EDITIONS as BODY_EDITIONS, CAVE_SIZE as BODY_SIZE
from .library_height_restore import ENCODED_HEIGHT_10, EDITION_HEIGHT

CONTROL_TABLES = {'original':0x433E50, 'best':0x434650, 'sp':0x4A76D0}
OPTICAL_HEIGHTS = {value: value-0x80 for value in range(0x8B,0x8F)}
NATIVE_CONTROL_BYTES = bytes.fromhex(
 '000082920070013c140022a601009426340022a4c2ff0010480020a600000000'
 '000082920070013c160022a60100942616002286360022a4b9ff0010480020a6'
 '000082920070013c180022a601009426380022a4b2ff0010480020a600000000'
 '000082920070013c1a0022a6010094263a0022a4aaff0010480020a600000000'
 '00008292320022a6a5ff001001009426')
NATIVE_GEOMETRY = (0x3C017000,0x8C230030,0x2402013F,0xAE030004,
                   0x3C017000,0x8E230020,0xAE030008,0x8C23003C,
                   0xAE03000C,0x3C017000)

def _words(*values):return struct.pack('<'+'I'*len(values),*values)
def _jump(address):return 2<<26|address>>2

def layout(edition):
    if BODY_SIZE!=44:raise ValueError('library row-tail ownership changed')
    handler=EDITION_HEIGHT[edition]
    return dict(base=handler-32,loop=handler-0x100,tail=BODY_EDITIONS[edition]['cave']+BODY_SIZE,
                table=CONTROL_TABLES[edition]+16,entry=handler-0x104,
                geometry=handler+0x690,count=handler+0x6E4,
                delta=BODY_EDITIONS[edition]['delta'])

def regions(edition):
    """(VA, original bytes, replacement bytes), all in existing file-backed space."""
    s=layout(edition);base,loop,tail=s['base'],s['loop'],s['tail']
    def ordinary(field,scratch):
        return _words(0x92820000,0x3C017000,0xA6220000|field,0xA4220000|scratch,
                      0xA6200048,_jump(loop),0x26940001)
    # The flag is independent of persistent/cached height, including native reset30.
    height=_words(0x92820000,0x2443FF75,0x2C630004,0xAFA30058,0xA3A20059,
                  0x2443FF76,0x2C630005,0x3041007F,0x0023100B,
                  0xA6220016,0x3C017000,0xA4220036,0xA6200048,
                  _jump(loop),0x26940001)
    controls=ordinary(0x14,0x34)+height+ordinary(0x18,0x38)+ordinary(0x1A,0x3A)
    # Parser invariant: flag1 implies explicit mode0 until glyph construction ends.
    # Removing redundant LUI leaves AT unchanged; count319 moves to the later LUI.
    geometry=_words(0x3C017000,0x8C230030,0x93A20058,0x00021400,0x00621823,
                    0xAE030004,0x8E230020,0xAE030008,0x8C23003C,0xAE03000C)
    palette=_words(0x92820000,0xA6220032,_jump(loop),0x26940001)
    assert len(controls)==len(NATIVE_CONTROL_BYTES)==144
    return [(base,NATIVE_CONTROL_BYTES,controls),(tail,bytes(16),palette),
            (s['table'],_words(*(base+32*i for i in range(5))),
             _words(base,base+28,base+88,base+116,tail)),
            (s['entry'],bytes(4),_words(0xAFA00058)),
            (s['geometry'],_words(*NATIVE_GEOMETRY),geometry),
            (s['count'],_words(0x3C017000),_words(0x2402013F))]+digit_regions(EDITION_HEIGHT[edition]-0x13A490)

def native_preimages(edition):return [(va,before) for va,before,_ in regions(edition)]
def write_ranges(edition):
    delta=layout(edition)['delta']
    return [(va-delta,va-delta+len(after)) for va,_,after in regions(edition)]

def apply_library_optical_metrics(executable:bytes,edition='original'):
    s=layout(edition);patches=regions(edition)
    current=[executable[va-s['delta']:va-s['delta']+len(after)] for va,_,after in patches]
    already=all(data==after for data,(_,_,after) in zip(current,patches))
    if not already and not all(data==before for data,(_,before,_) in zip(current,patches)):
        raise ValueError(f'{edition}: library optical metrics preimage drift or partial patch')
    out=bytearray(executable)
    for va,_,after in patches:out[va-s['delta']:va-s['delta']+len(after)]=after
    assert len(out)==len(executable)
    return bytes(out),dict(edition=edition,already_applied=already,unchanged_size=True,
        encoded_height10=ENCODED_HEIGHT_10,optical_height_operands={f'{k:02X}':v for k,v in OPTICAL_HEIGHTS.items()},
        glyph_record_y_delta=-1,pen_and_advance_unchanged=True,byte_line_scanners_unchanged=True,
        stack_flag_offset='0x58',explicit_height_marker_offset='0x59',
        automatic_compact_digits='width14/advance12/H9..12; H-1 unless explicit height set in this parser call',new_persistent_fields=False,new_memory_allocation=False,
        other_251_height_parameters_preserved=True,
        writes=[dict(offset=va-s['delta'],size=len(after),sha256=hashlib.sha256(after).hexdigest()) for va,_,after in patches])

def verify_library_optical_metrics(executable:bytes,edition='original'):
    _,report=apply_library_optical_metrics(executable,edition)
    if not report['already_applied']:raise ValueError(f'{edition}: library optical metrics patch missing')
    return report
