"""Analysis-only optical patch using existing file-backed native code space.
Repack controls32..36 into their original144 bytes plus checked16-byte tail.
Inline Y adjustment by removing redundant LUI and moving count constant later.
No new heap/BSS/ELF segment or harness helper addresses. Not production yet.
"""
import struct,json,hashlib
from pathlib import Path
from srwz.library_body_metrics import EDITIONS,CAVE_SIZE
from srwz.library_height_restore import addresses
from optical_candidate import words,jump
OUT=Path(__file__).parent

def candidate(elf,edition):
 handler,_=addresses(edition);d=handler-0x13a490;base=handler-32;loop=handler-0x100;spec=EDITIONS[edition];tail=spec['cave']+CAVE_SIZE
 inv=json.loads((OUT/'inventory.json').read_text());row=next(x for x in inv['editions'] if x['edition']==edition);table=int(row['control_table_va'],16);old=elf.words(table+4*4,5);assert old==tuple(base+32*i for i in range(5));assert elf.read(tail,16)==bytes(16)
 assert elf.words(0x13a38c+d,1)==(0,)
 # Whole geometry preimage and delayed count constant must remain native.
 geometry_va=0x13ab20+d;original_geometry=(0x3c017000,0x8c230030,0x2402013f,0xae030004,0x3c017000,0x8e230020,0xae030008,0x8c23003c,0xae03000c,0x3c017000)
 assert elf.read(geometry_va,40)==words(*original_geometry);assert elf.words(0x13ab74+d,1)==(0x3c017000,)
 # No branch may enter an interior instruction whose role is changed.
 incoming=[]
 for pc in range(0x13a290+d,0x13ac88+d,4):
  w=elf.words(pc,1)[0];op=w>>26;dest=None
  if op in (1,4,5,6,7,20,21,22,23):dest=pc+4+4*((w&65535)-65536 if w&32768 else w&65535)
  elif op in (2,3):dest=(w&0x3ffffff)<<2
  if dest is not None and geometry_va<dest<geometry_va+40:incoming.append((pc,dest))
 assert not incoming
 def ordinary(parameter_offset,scratch_offset):
  return words(0x92820000,0x3c017000,0xa6220000|parameter_offset,0xa4220000|scratch_offset,0xa6200048,jump(loop),0x26940001)
 width=ordinary(0x14,0x34)
 height=words(0x92820000,0x2443ff75,0x2c630004,0xafa30058,0x2443ff76,0x2c630005,0x3041007f,0x0023100b,0xa6220016,0x3c017000,0xa4220036,0xa6200048,jump(loop),0x26940001)
 space=ordinary(0x18,0x38);vertical=ordinary(0x1a,0x3a);packed=width+height+space+vertical+bytes(4);assert len(packed)==144
 palette=words(0x92820000,0xa6220032,jump(loop),0x26940001)
 targets=(base,base+28,base+84,base+112,tail)
 geometry=words(0x3c017000,0x8c230030,0x8fa20058,0x00021400,0x00621823,0xae030004,0x8e230020,0xae030008,0x8c23003c,0xae03000c)
 writes=[(base,packed),(tail,palette),(table+16,words(*targets)),(0x13a38c+d,words(0xafa00058)),(geometry_va,geometry),(0x13ab74+d,words(0x2402013f))]
 # Historical candidate is compared with its frozen eight-region handoff,
 # not a later production revision that adds automatic compact digits.
 frozen=json.loads((OUT.parent/'text-control-layout-handoff-20261021/snapshot.json').read_text())['native_patch_ledger'][edition]['writes']
 for va,after in writes:
  row=next(r for r in frozen if int(r['va'],16)==va)
  assert row['after_hex']==after.hex(),'historical optical candidate differs from frozen ledger'
 return dict(edition=edition,writes=writes,movn_pc=base+28+28,original_control_span_sha256=hashlib.sha256(elf.read(base,144)).hexdigest(),packed_span_sha256=hashlib.sha256(packed).hexdigest(),control_entries=list(map(hex,targets)),palette_tail=hex(tail),geometry_va=hex(geometry_va),all_writes_file_backed=all(len(elf.read(a,len(code)))==len(code) for a,code in writes))

def install(uc,elf,edition):
 from numeric_harness import GPRS
 from unicorn import UC_HOOK_CODE
 proof=candidate(elf,edition)
 for address,code in proof['writes']:uc.mem_write(address,code)
 pc=proof['movn_pc'];uc.mem_write(pc,b'\0'*4)
 def movn(machine,address,size,data):
  if machine.reg_read(GPRS[3])!=0:machine.reg_write(GPRS[2],machine.reg_read(GPRS[1]))
 uc.hook_add(UC_HOOK_CODE,movn,begin=pc,end=pc)
 return proof
