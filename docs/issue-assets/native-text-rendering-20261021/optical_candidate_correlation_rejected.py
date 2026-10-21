"""Analysis-only EE candidate: optical height operands and per-record Y=-1.
Not a production patch allocator. Helpers live in harness-owned 0x1700000 RAM.
8A restores10; 8B..8E select11..14 and a transient scratch-only optical marker.
Explicit height remains decoded, pen stays unchanged, no new persistent fields.
"""
import struct
from srwz.library_height_restore import addresses,NATIVE_WORDS
GEOMETRY_HELPER=0x1700000
HEIGHT_HELPER=0x1700100

def words(*w):return struct.pack('<'+'I'*len(w),*w)
def jump(a):return 2<<26|a>>2

def candidate(elf,edition):
    handler,_=addresses(edition);delta=handler-0x13a490;record=0x13ab24+delta
    assert elf.read(handler,32)==words(*NATIVE_WORDS),'native height handler drift'
    assert elf.read(record,8)==words(0x8c230030,0x2402013f),'native record writer drift'
    height=words(
        0x92820000,  # lbu v0,0(s4): raw parameter
        0x2443ff76,  # addiu v1,v0,-8A
        0x2c630005,  # sltiu v1,v1,5: reserved8A..8E only
        0x3041007f,  # andi at,v0,7F
        0x0023100b,  # movn v0,at,v1: persistent height decoded
        0xa6220016,  # sh v0,16(s1)
        0x92810000,  # lbu at,0(s4): raw parameter
        0x3823008a,  # xori v1,at,8A
        0x0023100b,  # movn v0,at,v1: scratch keeps8B..8E;8A stays10
        0x3c017000,  # lui at,7000
        0xa4220036,  # sh v0,36(at): working height
        0xa6200048,  # sh zero,48(s1)
        jump(handler-0x100),
        0x26940001,  # addiu s4,1, branch delay
    )
    geometry=words(
        0x8422003e,  # lh v0,3E(at): selected glyph height
        0x86240016,  # lh a0,16(s1): decoded explicit height
        0x00441023,  # subu v0,v0,a0
        0x2442ff80,  # addiu v0,-128: optical marker only
        0x14400007,  # bnez v0,return
        0,
        0x86220048,  # lh v0,48(s1): classification must be off
        0x14400004,  # bnez v0,return
        0,
        0xa424003e,  # sh a0,3E(at): decoded record height
        0x3c020001,  # lui v0,1: delta in packed XY high half
        0x00621823,  # subu v1,v1,v0: Y-1, X unchanged
        jump(record+8),
        0x2402013f,  # displaced count constant, branch delay
    )
    return {'edition':edition,'geometry_helper':GEOMETRY_HELPER,'height_helper':HEIGHT_HELPER,
        'writes':[(handler,words(jump(HEIGHT_HELPER),0)),
                  (record,words(jump(GEOMETRY_HELPER),0x8c230030)),
                  (HEIGHT_HELPER,height),(GEOMETRY_HELPER,geometry)],
        'movn_pcs':[HEIGHT_HELPER+16,HEIGHT_HELPER+32]}

def install(uc,elf,edition):
    from numeric_harness import GPRS
    from unicorn import UC_HOOK_CODE
    proof=candidate(elf,edition)
    for address,code in proof['writes']:uc.mem_write(address,code)
    for pc in proof['movn_pcs']:uc.mem_write(pc,b'\0'*4)
    def movn(machine,pc,size,data):
        if pc in proof['movn_pcs'] and machine.reg_read(GPRS[3])!=0:
            machine.reg_write(GPRS[2],machine.reg_read(GPRS[1]))
    uc.hook_add(UC_HOOK_CODE,movn)
    return proof
