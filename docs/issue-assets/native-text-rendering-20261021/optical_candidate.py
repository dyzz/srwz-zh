"""Analysis-only EE candidate: optical height operands and per-record Y=-1.
Not a production patch allocator. Helpers live in harness-owned 0x1700000 RAM.
8A restores10; 8B..8E select11..14 with a call-local SP+58 optical flag.
Both persistent and working height remain decoded; pen stays unchanged.
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
    entry_flag=0x13a38c+delta
    assert elf.read(entry_flag,4)==words(0),'native entry padding drift'
    height=words(
        0x92820000,  # lbu v0,0(s4): raw parameter
        0x2443ff75,  # addiu v1,v0,-8B
        0x2c630004,  # sltiu v1,v1,4: optical8B..8E
        0xafa30058,  # sw v1,58(sp): call-local optical flag
        0x2443ff76,  # addiu v1,v0,-8A
        0x2c630005,  # sltiu v1,v1,5: encoded8A..8E
        0x3041007f,  # andi at,v0,7F
        0x0023100b,  # movn v0,at,v1: decode height
        0xa6220016,  # sh v0,16(s1)
        0x3c017000,  # lui at,7000
        0xa4220036,  # sh v0,36(at): decoded working height
        0xa6200048,  # sh zero,48(s1)
        jump(handler-0x100),
        0x26940001,  # addiu s4,1, branch delay
    )
    geometry=words(
        0x8fa20058,  # lw v0,58(sp): call-local optical flag
        0x10400006,  # beqz v0,return
        0,
        0x86220048,  # lh v0,48(s1): classification must be off
        0x14400003,  # bnez v0,return
        0,
        0x3c020001,  # lui v0,1: packed XY high-half delta
        0x00621823,  # subu v1,v1,v0: Y-1, X unchanged
        jump(record+8),
        0x2402013f,  # displaced count constant, branch delay
    )
    return {'edition':edition,'geometry_helper':GEOMETRY_HELPER,'height_helper':HEIGHT_HELPER,
        'writes':[(entry_flag,words(0xafa00058)),(handler,words(jump(HEIGHT_HELPER),0)),
                  (record,words(jump(GEOMETRY_HELPER),0x8c230030)),
                  (HEIGHT_HELPER,height),(GEOMETRY_HELPER,geometry)],
        'movn_pcs':[HEIGHT_HELPER+28]}

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
