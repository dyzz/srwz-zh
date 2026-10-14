"""SP experiment: marked captions bypass destination alpha and depth tests.
Only new caption primitives use mode bit7. The ordinary VEFF packet is unchanged.
Code is mapped from unused ELF header padding into prototype reserved scratch RAM.
"""
import struct
BASE=0xff680
HOOK=0x1b08d8
CAVE=0x1f00100
SIZE=44
FILE_OFFSET=0x920

def patch(elf):
 assert elf[HOOK-BASE:HOOK-BASE+8]==struct.pack('<2I',0x90430001,0x30630007)
 words=[0x90430001,0x30630080,0x10600003,0,
        0x3c030003,0xfea3fff0,
        0x90430001,0x30630007,0x08000000|((HOOK+8)>>2),0,0]
 assert len(words)*4==SIZE
 assert elf[FILE_OFFSET:FILE_OFFSET+SIZE]==bytes(SIZE)
 ph=struct.unpack_from('<I',elf,28)[0]
 assert struct.unpack_from('<8I',elf,ph+70*32)[4:6]==(0,0)
 struct.pack_into('<8I',elf,ph+70*32,1,FILE_OFFSET,CAVE,CAVE,SIZE,SIZE,7,16)
 elf[FILE_OFFSET:FILE_OFFSET+SIZE]=struct.pack('<11I',*words)
 struct.pack_into('<2I',elf,HOOK-BASE,0x08000000|(CAVE>>2),0)
 return {'hook':hex(HOOK),'cave':hex(CAVE),'marker':'primitive byte1 bit7','test':'ATE=0 DATE=0 ZTST=ALWAYS for marked captions'}
