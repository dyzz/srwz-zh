"""Native intra-window CFG for both atlas scheduling/submission callers.
Branches and delay slots are represented as atomic instruction pairs; all
returning direct calls have continuation edges. No indirect target invention.
Dominance is conditional on ordinary call/return behavior; callee side effects,
frame entry selection, hardware polling and asynchronous timing are not proved.
"""
from pathlib import Path
import json,hashlib,sys
from inventory import native,decode
sys.path.insert(0,'/tmp/srwz-font-audit-deps');import capstone
OUT=Path(__file__).parent;trans=json.loads((OUT/'transfer-inventory.json').read_text());sub=json.loads((OUT/'submission-inventory.json').read_text());res=json.loads((OUT/'resource-inventory.json').read_text());results=[];md=capstone.Cs(capstone.CS_ARCH_MIPS,capstone.CS_MODE_MIPS64|capstone.CS_MODE_LITTLE_ENDIAN)
def target(pc,w):return ((pc+4)&0xf0000000)|((w&0x3ffffff)<<2)
def sx(w):return (w&65535)-65536 if w&32768 else w&65535
def flow(w):
 op=w>>26;rs=w>>21&31;fn=w&63
 if op==3:return 'call'
 if op==2:return 'jump'
 if op in (1,4,5,6,7,20,21,22,23) or op in (16,17,18) and rs==8:return 'conditional'
 if op==0 and fn==8:return 'indirect_jump'
 if op==0 and fn==9:return 'indirect_call'
 return 'ordinary'
for ed in ('original','best','sp'):
 e,lock=native(ed);t=next(x for x in trans['editions'] if x['edition']==ed);s=next(x for x in sub['editions'] if x['edition']==ed);r=next(x for x in res['editions'] if x['edition']==ed);send=int(s['functions']['send_chain']['entry'],16);cache=int(s['functions']['cache_syscall']['entry'],16);scatter=int(r['functions']['scatter']['entry'],16);builder=int(t['transfer_builder'],16);windows=[];listing=[]
 for index,b in enumerate(t['blocks']):
  gate=int(b['start'],16);scatter_sites=[int(x,16) for x in r['functions']['scatter']['callers'] if abs(int(x,16)-gate)<0x1000];assert len(scatter_sites)==1;scatter_site=scatter_sites[0]
  send_sites=[pc for pc in range(gate,gate+0x1000,4) if e.words(pc,1)[0]>>26==3 and target(pc,e.words(pc,1)[0])==send];assert len(send_sites)==2,(ed,index,send_sites)
  start=min(gate,scatter_site);end=send_sites[-1]+8;instructions={pc:e.words(pc,1)[0] for pc in range(start,end,4)};delays=set();calls=[];unresolved=[]
  for pc,w in instructions.items():
   kind=flow(w)
   if kind!='ordinary':
    assert flow(instructions.get(pc+4,0))=='ordinary',(ed,hex(pc),'control flow in delay slot');delays.add(pc+4)
   if kind=='call':calls.append(dict(site=hex(pc),target=hex(target(pc,w)),label={send:'dma_send',cache:'cache_syscall100',scatter:'cpu_scatter',builder:'atlas_packet_builder'}.get(target(pc,w),'opaque_returning_callee')))
   if kind.startswith('indirect'):unresolved.append(dict(site=hex(pc),kind=kind))
  graph={};exits=[]
  for pc,w in instructions.items():
   if pc in delays:continue
   kind=flow(w)
   if kind=='conditional':edges=[pc+4+4*sx(w),pc+8]
   elif kind=='jump':edges=[target(pc,w)]
   elif kind in ('call','indirect_call'):edges=[pc+8]
   elif kind=='indirect_jump':edges=[]
   else:edges=[pc+4]
   graph[pc]=edges
   for dest in edges:
    if dest!=end and dest not in instructions:exits.append(dict(site=hex(pc),target=hex(dest)))
    assert dest not in delays,(ed,index,'entry into delay slot',hex(dest))
  assert not unresolved and not exits,(ed,index,'incomplete local CFG',unresolved,exits)
  graph[end]=[];reachable=set();todo=[start]
  while todo:
   pc=todo.pop()
   if pc in reachable:continue
   reachable.add(pc);todo.extend(graph[pc])
  pred={pc:set() for pc in reachable}
  for pc in reachable:
   for d in graph[pc]:pred[d].add(pc)
  dom={pc:({pc} if pc==start else set(reachable)) for pc in reachable};changed=True
  while changed:
   changed=False
   for pc in sorted(reachable):
    if pc==start:continue
    new={pc}|set.intersection(*(dom[p] for p in pred[pc]));changed|=new!=dom[pc];dom[pc]=new
  cache_sites=[int(c['site'],16) for c in calls if c['label']=='cache_syscall100'];assert len(cache_sites)==2
  assert all(scatter_site in dom[pc] for pc in send_sites),(ed,index,'scatter must dominate both sends')
  assert all(cache_sites[i] in dom[pc] for i,pc in enumerate(send_sites)),(ed,index,'cache call must dominate corresponding send')
  def reaches(a,b):
   seen=set();todo=[a]
   while todo:
    p=todo.pop()
    if p==b:return True
    if p in seen:continue
    seen.add(p);todo.extend(graph[p])
   return False
  builder_sites=[int(c['site'],16) for c in calls if c['label']=='atlas_packet_builder'];assert len(builder_sites)==2
  order='request_then_scatter_then_submit' if scatter_site>builder_sites[-1] else 'scatter_then_request_then_submit'
  if index==0:assert all(reaches(pc,scatter_site) and not reaches(scatter_site,pc) for pc in builder_sites)
  else:assert all(scatter_site in dom[pc] and not reaches(pc,scatter_site) for pc in builder_sites)
  listing.append(f'\n; caller window{index}: {order}')
  for pc,w in instructions.items():listing.append(f'{pc:08x} {w:08x} {decode(md,w,pc)[0]}')
  windows.append(dict(index=index,start=hex(start),end=hex(end),sha256=hashlib.sha256(e.read(start,end-start)).hexdigest(),scheduling_gate=hex(gate),scatter_site=hex(scatter_site),send_sites=list(map(hex,send_sites)),cache_sites=list(map(hex,cache_sites)),order=order,reachable_macro_nodes=len(reachable),unresolved_transfers=unresolved,external_direct_edges=exits,calls=calls,edges={hex(pc):list(map(hex,ds)) for pc,ds in graph.items()},dominance_claims=[dict(send_site=hex(pc),scatter_dominates=True,corresponding_cache_call_dominates=True) for pc in send_sites]))
 (OUT/f'{ed}-frame-upload-windows.asm').write_text('\n'.join(listing)+'\n');results.append(dict(edition=ed,native_executable=lock,windows=windows));print(ed,'two native scheduling/scatter/cache/send CFG windows closed; orders differ',flush=True)
(OUT/'frame-flow-inventory.json').write_text(json.dumps(dict(scope=__doc__,status='six_native_intra_window_CFGs_close_and_verify_scatter_cache_submission_dominance_under_returning_call_contracts',editions=results),indent=2)+'\n')
