"""Revalidated direct measure-call census with bounded local argument/return use.
Executable-section JAL/J patterns are static candidates, not whole-program
reachability. Argument inference stops at prior transfers/unknown definitions;
return inspection stops at first use/overwrite/control boundary. No pointer or
callee ownership is inferred from a register copy. Indirect calls stay open.
"""
from pathlib import Path
from collections import Counter
import json,sys,hashlib
from inventory import native,decode
sys.path.insert(0,'/tmp/srwz-font-audit-deps')
import capstone
OUT=Path(__file__).parent
md=capstone.Cs(capstone.CS_ARCH_MIPS,capstone.CS_MODE_MIPS64|capstone.CS_MODE_LITTLE_ENDIAN)
old=json.loads((OUT/'caller-inventory.json').read_text());results=[]
def transfer(w):
 op=w>>26
 return op in (1,2,3,4,5,6,7,20,21,22,23) or op==0 and w&63 in (8,9) or op in (16,17,18) and ((w>>21)&31)==8
# Explicit GPR read/write roles used only to locate the first use; unfamiliar
# instructions end inference. This avoids pretending Capstone supplies MIPS
# register-access metadata (it does not implement regs_access for this arch).
def roles(w):
 op=w>>26;rs=w>>21&31;rt=w>>16&31;rd=w>>11&31;fn=w&63
 if w==0:return set(),set()
 if op==0:
  if fn in (0,2,3,56,58,59,60,62,63):return {rt},{rd}
  if fn in (4,6,7,10,11,20,22,23,32,33,34,35,36,37,38,39,42,43,44,45,46,47):return {rs,rt},{rd}
  if fn in (8,9):return {rs},{31} if fn==9 else set()
  if fn in (16,18):return set(),{rd}
  if fn in (17,19):return {rs},set()
  if fn in (24,25,26,27,28,29,30,31):return {rs,rt},set()
 if op in (8,9,10,11,12,13,14,24,25):return {rs},{rt}
 if op==15:return set(),{rt}
 if op in (4,5,20,21):return {rs,rt},set()
 if op in (1,6,7,22,23):return {rs},set()
 if op in (2,3):return set(),{31} if op==3 else set()
 if op in (30,32,33,34,35,36,37,38,39,55):return {rs},{rt}
 if op in (31,40,41,42,43,44,45,46,63):return {rs,rt},set()
 if op in (49,53):return {rs},set()
 if op in (57,61):return {rs},set()
 if op in (16,17,18):
  if rs in (0,1,2):return set(),{rt}
  if rs in (4,5,6):return {rt},set()
  if op==17 and rs>=16:return set(),set() # FPU arithmetic, no GPR access
 return None
for edition in old['editions']:
 ed=edition['edition'];e,lock=native(ed);rows=[]
 for call in edition['direct_transfer_candidates']:
  if call['target']!='measure':continue
  site=int(call['site'],16);w=e.words(site,1)[0];assert w>>26 in (2,3) and (w&0x3ffffff)<<2==int(call['target_va'],16)
  constant=None;definition=None;reason='no local definition before boundary'
  for pc in [site+4]+list(range(site-4,site-132,-4)):
   value=e.words(pc,1)[0]
   if pc<site and transfer(value):reason='prior transfer';break
   rw=roles(value)
   if rw is None:reason='unknown register effects';break
   if 5 not in rw[1]:continue
   definition=pc;op=value>>26;rs=value>>21&31;rt=value>>16&31;fn=value&63
   if op in (9,25) and rs==0:constant=(value&65535)-65536 if value&32768 else value&65535
   elif op==13 and rs==0:constant=value&65535
   elif op==0 and fn in (33,37,45) and rs==0 and rt==0:constant=0
   reason='constant local definition' if constant is not None else 'nonconstant local definition';break
  path=[];first=None;stop='window limit';pending_boundary=False
  for pc in range(site+8,site+8+128,4):
   value=e.words(pc,1)[0];asm=decode(md,value,pc)[0];rw=roles(value);path.append(dict(pc=hex(pc),word=hex(value),asm=asm,in_transfer_delay_slot=pending_boundary))
   if rw is None:stop='unknown register effects';break
   if 2 in rw[0]:first=path[-1];stop='first V0 read';break
   if 2 in rw[1]:stop='V0 overwritten before local read';break
   if pending_boundary:stop='control boundary including delay slot before local read';break
   if transfer(value):pending_boundary=True
  shape=first['asm'].split()[0] if first else stop
  rows.append(dict(site=hex(site),kind=call['kind'],local_mode_constant=constant,mode_definition=hex(definition) if definition else None,mode_inference=reason,argument_window_sha256=hashlib.sha256(e.read(site-128,136)).hexdigest(),mode_semantics='negative_half_advance' if constant==0 else 'total_advance' if constant is not None else 'unresolved',first_return_use=first,return_observation_stop=stop,first_return_shape=shape,return_path=path,call_and_postwindow_sha256=hashlib.sha256(e.read(site,136)).hexdigest()))
 assert all(x['first_return_use'] is not None and x['local_mode_constant'] in (0,1) for x in rows),(ed,'unresolved local slice')
 modes=Counter(str(x['local_mode_constant']) for x in rows);shapes=Counter(x['first_return_shape'] for x in rows);results.append(dict(edition=ed,native_executable=lock,direct_candidate_count=len(rows),local_mode_counts=dict(modes),first_return_shapes=dict(shapes),calls=rows));print(ed,len(rows),'mode',dict(modes),'first uses',dict(shapes),flush=True)
(OUT/'measure-consumer-inventory.json').write_text(json.dumps(dict(scope=__doc__,editions=results),indent=2)+'\n')
