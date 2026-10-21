"""Synchronize explicit font metrics at the encyclopedia-only scrolling row call.

The original row initializer sets classified metrics but leaves explicit metrics
from prior fields. Width/space controls select those stale explicit metrics.
This tail trampoline copies the row's own four metric bytes before the original
initializer. Native control parsing, classified mode, row spacing and dialogue
call sites stay intact. Each edition uses independently checked code addresses.
"""
from __future__ import annotations
import hashlib
import struct

EDITIONS = {
    'original': dict(delta=0xFE580, hook=0x221220, draw=0x220DB0, cave=0x44BC44,
                     state=0x46E344),
    'best': dict(delta=0xFE580, hook=0x2215E0, draw=0x221170, cave=0x44C444,
                 state=0x46EB44),
    # SP addresses/data are checked against its own original executable.
    'sp': dict(delta=0xFF680, hook=0x226000, draw=0x225B90, cave=0x4CAD44,
               state=0x4ED5C4),
}
CAVE_SIZE = 0x2C  # Exact 11-word tail; following 16 bytes belong to safe-height restore.

def _j(op, target):
    return op << 26 | (target >> 2 & 0x3FFFFFF)

def trampoline(edition):
    s=EDITIONS[edition]; base=s['state']; high=(base+0x8000)>>16
    words=[0x3C010000|high]  # lui at, font-state high
    for field in range(4):
        words.append(0x91030000 | (0x0E+field))  # lbu v1, descriptor byte(t0)
        words.append(0xA4230000 | ((base+field*2)&0xFFFF)) # sh v1, explicit dimension(at)
    words.extend([_j(2,s['draw']),0])  # preserve jal's ra; original callee returns to row loop
    return struct.pack('<'+str(len(words))+'I',*words).ljust(CAVE_SIZE,b'\0')

def write_ranges(edition):
    s=EDITIONS[edition];return [(s['hook']-s['delta'],s['hook']-s['delta']+4),
                              (s['cave']-s['delta'],s['cave']-s['delta']+CAVE_SIZE)]

def apply_library_body_metrics(executable: bytes, edition='original'):
    s=EDITIONS[edition];h,c=[lo for lo,hi in write_ranges(edition)]
    pre=struct.pack('<I',_j(3,s['draw']));after=struct.pack('<I',_j(3,s['cave']));code=trampoline(edition)
    if executable[h-8:h]!=bytes.fromhex('2d4080022110c200') or executable[h+4:h+8]!=bytes.fromhex('000040a0'):
        raise ValueError(f'{edition}: encyclopedia row call arguments/delay-slot drift')
    before=executable[h:h+4];tail=executable[c:c+CAVE_SIZE]
    already=before==after and tail==code
    if not already and (before!=pre or tail!=bytes(CAVE_SIZE)):
        raise ValueError(f'{edition}: encyclopedia metrics hook/cave preimage drift')
    out=bytearray(executable);out[h:h+4]=after;out[c:c+CAVE_SIZE]=code
    assert len(out)==len(executable)
    return bytes(out),dict(edition=edition,hook_va=hex(s['hook']),cave_va=hex(s['cave']),
                          already_applied=already,trampoline_sha256=hashlib.sha256(code).hexdigest(),
                          policy='sync_explicit_metrics_from_each_encyclopedia_row_descriptor',
                          preserved_native_classification=True,unchanged_size=True,
                          writes=[dict(offset=lo,size=hi-lo) for lo,hi in write_ranges(edition)])

def verify_library_body_metrics(executable: bytes, edition='original'):
    _,report=apply_library_body_metrics(executable,edition)
    if not report['already_applied']:raise ValueError(f'{edition}: library body metrics patch missing')
    return report
