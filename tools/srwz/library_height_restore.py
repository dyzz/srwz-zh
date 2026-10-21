"""Encode height10 as 0x8A without placing a raw LF in C-string body controls.

The stock 0x33 handler still accepts every other parameter unchanged. Reserved
0x8A now means 10 instead of 138. Native explicit setters are unaffected.
Uses the 16 zero bytes immediately after the exact library-row trampoline.
"""
from __future__ import annotations
import hashlib
import struct
from .library_body_metrics import EDITIONS as BODY_EDITIONS, CAVE_SIZE as BODY_SIZE

ENCODED_HEIGHT_10 = 0x8A
EDITION_HEIGHT = {'original':0x13A490, 'best':0x13A490, 'sp':0x13AF30}
CAVE_SIZE = 16
NATIVE_WORDS = (0x92820000,0x3C017000,0xA6220016,0x26940001,
                0x86220016,0xA4220036,0x1000FFB9,0xA6200048)

def _words(*values):return struct.pack('<'+'I'*len(values),*values)
def addresses(edition):
    assert BODY_SIZE == 44, 'row tail layout changed'
    return EDITION_HEIGHT[edition],BODY_EDITIONS[edition]['cave']+BODY_SIZE

def handler_code(edition):
    handler,cave=addresses(edition)
    return _words(0x92820000,2<<26|cave>>2,0xA6200048,0xA6220016,
                  0x3C017000,0xA4220036,0x1000FFB9,0x26940001)

def cave_code(edition):
    handler,_=addresses(edition)
    # xori v1,v0,8A; andi at,v0,7F; j handler+0C; movz v0,at,v1.
    # Only the encoded 8A satisfies movz; the handler rebuilds scratch AT.
    return _words(0x3843008A,0x3041007F,2<<26|(handler+12)>>2,0x0023100A)

def write_ranges(edition):
    handler,cave=addresses(edition);delta=BODY_EDITIONS[edition]['delta']
    return [(handler-delta,handler-delta+32),(cave-delta,cave-delta+CAVE_SIZE)]

def apply_library_height_restore(executable:bytes,edition='original'):
    handler,cave=addresses(edition);(h,_),(c,_)=write_ranges(edition)
    before=executable[h:h+32];tail=executable[c:c+CAVE_SIZE]
    replacement=handler_code(edition);helper=cave_code(edition)
    already=before==replacement and tail==helper
    if not already and (before!=_words(*NATIVE_WORDS) or tail!=bytes(CAVE_SIZE)):
        raise ValueError(f'{edition}: safe library height handler/cave preimage drift')
    out=bytearray(executable);out[h:h+32]=replacement;out[c:c+CAVE_SIZE]=helper
    assert len(out)==len(executable)
    return bytes(out),dict(edition=edition,handler_va=hex(handler),cave_va=hex(cave),
        encoded_height=ENCODED_HEIGHT_10,decoded_height=10,already_applied=already,
        other_height_parameters_preserved=True,byte_line_scanners_unchanged=True,
        helper_sha256=hashlib.sha256(helper).hexdigest(),unchanged_size=True,
        writes=[dict(offset=a,size=b-a) for a,b in write_ranges(edition)])

def verify_library_height_restore(executable:bytes,edition='original'):
    _,report=apply_library_height_restore(executable,edition)
    if not report['already_applied']:raise ValueError(f'{edition}: safe library height restore missing')
    return report
