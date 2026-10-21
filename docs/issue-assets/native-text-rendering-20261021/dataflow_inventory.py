"""Conservative straight-line native address propagation for font/substitution refs.
ELF GP comes from .reginfo. Branch targets and post-delay boundaries reset all
non-GP facts; unknown instructions reset all facts. Calls include delay-slot
arguments, then forget caller/callee values rather than assume ABI preservation.
No merged CFG facts, loaded-pointer propagation or runtime reachability proof.
"""
from pathlib import Path
import json,struct,ctypes,sys
from inventory import native,decode,REG
sys.path.insert(0,'/tmp/srwz-font-audit-deps');import capstone
OUT=Path(__file__).parent;inv=json.loads((OUT/'inventory.json').read_text());md=capstone.Cs(capstone.CS_ARCH_MIPS,capstone.CS_MODE_MIPS64|capstone.CS_MODE_LITTLE_ENDIAN)
results=[]
def sx16(w):return ctypes.c_int16(w&65535).value
def sections(e):
 off=struct.unpack_from('<I',e.b,32)[0];size,n=struct.unpack_from('<HH',e.b,46);return [struct.unpack_from('<10I',e.b,off+i*size) for i in range(n)]
for ed in ('original','best','sp'):
 e,lock=native(ed);r=next(x for x in inv['editions'] if x['edition']==ed);F=int(r['state_va'],16);subs=[];ss=sections(e)
 gpsections=[s for s in ss if s[1]==0x70000006];assert len(gpsections)==1;gp=struct.unpack_from('<I',e.b,gpsections[0][4]+20)[0]
 for i in range(4):
  h=int(r['controls'][12+i]['target'],16);subs.append(((e.words(h+0x14,1)[0]&65535)<<16)+sx16(e.words(h+0x1c,1)[0]))
 def classify(address):
  if F-16<=address<F+0x90:return {'region':'font_state','offset':hex(address-F)}
  if subs[0]-32<=address<subs[-1]+64:return {'region':'substitution_neighborhood','offset_from_first':address-subs[0]}
  return None
 def event(pc,kind,address,**kw):
  cl=classify(address)
  if cl:refs.append(dict(site=hex(pc),kind=kind,address=hex(address),asm=decode(md,e.words(pc,1)[0],pc)[0],**cl,**kw))
 refs=[];calls=[];watched=[]
 preset=next(x for x in json.loads((OUT/'preset-inventory.json').read_text())['editions'] if x['edition']==ed)
 writer=next(x for x in json.loads((OUT/'name-writer-inventory.json').read_text())['editions'] if x['edition']==ed)
 watch={int(preset['entry'],16):'font_preset',int(writer['entry'],16):'name_confirmation_writer'}
 for s in ss:
  if not s[2]&4 or s[1]==8:continue
  words={s[3]+p-s[4]:struct.unpack_from('<I',e.b,p)[0] for p in range(s[4],s[4]+s[5]-3,4)};targets=set()
  for pc,w in words.items():
   op=w>>26
   if op in (1,4,5,6,7,20,21,22,23):targets.add(pc+4+4*sx16(w))
   if op in (2,3):targets.add(((pc+4)&0xf0000000)|((w&0x3ffffff)<<2))
  regs={0:(0,[]),28:(gp,['ELF.reginfo.GP'])};pending=None
  def reset():return {0:(0,[]),28:(gp,['ELF.reginfo.GP'])}
  for pc,w in words.items():
   if pc in targets and not (pending and pc==pending[0]+4):regs=reset()
   op=w>>26;rs=(w>>21)&31;rt=(w>>16)&31;rd=(w>>11)&31;fun=w&63;old=dict(regs);new=None;dest=None;recognized=True
   def fact(reg):return old.get(reg)
   def calc(a,b,fn):
    aa,bb=fact(a),fact(b)
    return ((fn(aa[0],bb[0])&0xffffffff),aa[1]+bb[1]+[hex(pc)]) if aa and bb else None
   if op==15:dest=rt;new=((w&65535)<<16,[hex(pc)])
   elif op in (8,9,0x19):
    dest=rt;a=fact(rs);new=((a[0]+sx16(w))&0xffffffff,a[1]+[hex(pc)]) if a else None
   elif op in (12,13,14):
    dest=rt;a=fact(rs)
    if a:new=(((a[0]&(w&65535)) if op==12 else (a[0]|(w&65535)) if op==13 else (a[0]^(w&65535))),a[1]+[hex(pc)])
   elif op in (0x20,0x21,0x23,0x24,0x25,0x27,0x28,0x29,0x2b,0x37,0x3f,0x1e,0x1f):
    base=fact(rs);store=op in (0x28,0x29,0x2b,0x3f,0x1f)
    if base:
     address=(base[0]+sx16(w))&0xffffffff;value=fact(rt);event(pc,'store' if store else 'load',address,provenance=base[1],source_register=REG[rt],known_value=hex(value[0]) if store and value else None)
    if not store:dest=rt
   elif op==0:
    if fun in (0x20,0x21,0x2c,0x2d):dest=rd;new=calc(rs,rt,lambda a,b:a+b)
    elif fun in (0x22,0x23,0x2e,0x2f):dest=rd;new=calc(rs,rt,lambda a,b:a-b)
    elif fun in (0x24,0x25,0x26,0x27):
     dest=rd;new=calc(rs,rt,{0x24:lambda a,b:a&b,0x25:lambda a,b:a|b,0x26:lambda a,b:a^b,0x27:lambda a,b:~(a|b)}[fun])
    elif fun in (0,2,3):
     dest=rd;a=fact(rt);sh=(w>>6)&31
     if a:new=(((a[0]<<sh) if fun==0 else (a[0]>>sh) if fun==2 else (ctypes.c_int32(a[0]).value>>sh))&0xffffffff,a[1]+[hex(pc)])
    elif fun in (8,9):pass
    elif fun in (4,6,7,10,11,16,18,0x2a,0x2b,0x14,0x16,0x17,0x38,0x3a,0x3b,0x3c,0x3e,0x3f):dest=rd
    elif fun in (0x18,0x19):dest=rd if rd else None
    elif fun in (0x11,0x13,0x1a,0x1b,0xf):pass
    else:recognized=False
   elif op in (1,2,3,4,5,6,7,20,21,22,23):pass
   elif op in (10,11):dest=rt
   else:recognized=False
   if not recognized:regs=reset()
   if dest:
    regs.pop(dest,None)
    if new:
     regs[dest]=new;event(pc,'materialized_address',new[0],register=REG[dest],provenance=new[1])
   regs[0]=(0,[])
   if pending and pc==pending[0]+4:
    branchpc,branchw=pending
    if branchw>>26==3:
     args={REG[j]:{'address':hex(regs[j][0]),'provenance':regs[j][1],**classify(regs[j][0])} for j in range(4,12) if j in regs and classify(regs[j][0])}
     target=((branchpc+4)&0xf0000000)|((branchw&0x3ffffff)<<2)
     if target in watch:watched.append({'site':hex(branchpc),'target':watch[target],'arguments':{REG[j]:{'value':hex(regs[j][0]),'provenance':regs[j][1]} if j in regs else None for j in range(4,12)}})
     if args:calls.append({'site':hex(branchpc),'target':hex(((branchpc+4)&0xf0000000)|((branchw&0x3ffffff)<<2)),'arguments':args})
    regs=reset();pending=None
   if op in (1,2,3,4,5,6,7,20,21,22,23) or (op==0 and fun in (8,9)):pending=(pc,w)
 results.append({'edition':ed,'native_executable':lock,'GP':hex(gp),'font_state':hex(F),'substitution_buffers':[hex(x) for x in subs],'references':refs,'calls_with_region_arguments':calls,'watched_calls':watched})
 from collections import Counter
 print(ed,'refs',dict(Counter((x['region'],x['kind']) for x in refs)),'calls with tracked args',len(calls),'watched calls',len(watched),flush=True)
(OUT/'dataflow-inventory.json').write_text(json.dumps({'scope':__doc__,'editions':results},indent=2)+'\n')
