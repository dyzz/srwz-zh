"""One bounded dispatcher and payload for multiple verified text owners.

Routes remain explicit evidence-backed owners. They are not universal address
ranges, and do not claim every instance of the named surface is covered.
"""
import struct
from .proportional_hooks import Asm,draw_hook,measure_hook,cjk_runtime_table
from .proportional_metrics import runtime_table
from .proportional_payload import LAYOUTS

SITES={'best':(0x13ab58,0x139b78,0x139d08),'original':(0x13ab58,0x139b78,0x139d08),'sp':(0x13b5f8,0x13a618,0x13a7a8)}
SP_REPLAY_ROUTES=(
 dict(name='library_character',scene='library_character',draw=(0x62ec60,0x62ed60),measure=(0xd6d8c0,0xd6dac4),caller=0x22a33c),
 dict(name='synopsis',scene='sp_flow',draw=(0x8093e0,0x80956a),measure=(0x8093e0,0x80956a),caller=0x1ab058),
 dict(name='weapon_list',scene='weapon',draw=(0x7e6590,0x7e65b0),measure=(0x7e6590,0x7e65b0),caller=0x434dec),
)

def dispatcher(routes,targets,fallback,kind):
 a=Asm();source='s4' if kind=='draw' else 'a0'
 # Preserve full EE values even for fallback/other owners.
 a.i(9,'sp','sp',-32);a.i(0x1f,'sp','at',0);a.i(0x1f,'sp','t8',16)
 def leave(target):
  a.i(0x1e,'sp','at',0);a.i(0x1e,'sp','t8',16);a.i(9,'sp','sp',32);a.jump(target)
 for i,(route,target) in enumerate(zip(routes,targets)):
  next_=f'next{i}';lo,hi=route[kind]
  if kind=='draw':
   a.li('at',route['caller']);a.branch(5,'ra','at',next_);lo+=2
  a.li('at',lo);a.r(source,'at','t8',0x2b);a.branch(5,'t8','zero',next_)
  a.li('at',hi-1 if kind=='measure' else hi);a.r(source,'at','t8',0x2b);a.branch(4,'t8','zero',next_)
  leave(target);a.label(next_)
 leave(fallback);return a.finish()

def build_routed_payload(registry,edition,routes,*,chinese_punctuation=False):
 if not routes:raise ValueError('At least one route required')
 c=LAYOUTS[edition];base=c['base'];site,loop,epilogue=SITES[edition]
 for kind in ('draw','measure'):
  for i,r in enumerate(routes):
   lo,hi=r[kind]
   if not 0<=lo<hi<=0x2000000:raise ValueError('Invalid owner bounds')
   for other in routes[:i]:
    x,y=other[kind]
    if max(lo,x)<min(hi,y) and (kind=='measure' or r['caller']==other['caller']):raise ValueError('Ambiguous owner routes')
 blob=bytearray();sections=[]
 def add(name,data):
  blob.extend(bytes((-len(blob))%16));address=base+len(blob);blob.extend(data)
  if len(blob)>c['capacity']:raise ValueError('Routed payload exceeds reserved capacity')
  sections.append(dict(name=name,address=address,size=len(data)));return address
 a=Asm();a.emit(0x8e230024);a.emit(0xae030014);a.jump(site+8);native_draw=add('native_draw',a.finish())
 a=Asm();a.i(0x24,'a0','t3',0);a.branch(4,'t3','zero','end');a.jump(loop+8);a.label('end');a.jump(epilogue);native_measure=add('native_measure',a.finish())
 draw_targets=[];measure_targets=[]
 for r in routes:
  profile=registry['profiles'][r['scene']];table=add(r['name']+'_metrics',runtime_table(profile));width=profile['glyphs']['A']['width']
  cjk_table=add(r['name']+'_cjk',cjk_runtime_table(profile)) if chinese_punctuation else None
  draw_targets.append(add(r['name']+'_draw',draw_hook(*r['draw'],table,width,site=site,caller=r['caller'],cjk_table=cjk_table)))
  measure_targets.append(add(r['name']+'_measure',measure_hook(*r['measure'],table,site=loop,epilogue=epilogue,cjk_table=cjk_table,state=0x46e330 if edition=='original' else 0x4ed5b0)))
 draw_dispatch=add('draw_dispatch',dispatcher(routes,draw_targets,native_draw,'draw'))
 measure_dispatch=add('measure_dispatch',dispatcher(routes,measure_targets,native_measure,'measure'))
 patches=[(site,bytes.fromhex('2400238e140003ae'),struct.pack('<II',0x08000000|(draw_dispatch>>2),0)),(loop,bytes.fromhex('00008b9062006011'),struct.pack('<II',0x08000000|(measure_dispatch>>2),0))]
 return bytes(blob),patches,dict(edition=edition,base=base,sections=sections,routes=list(routes),payloadBytes=len(blob),capacity=c['capacity'],fontSha256=registry['fontSha256'],chinesePunctuation=chinese_punctuation,scope='Explicit replay owners; not all instances of every surface')


def install_routed_payload(elf,registry,edition,routes,*,chinese_punctuation=False):
 from .proportional_payload import reserve_payload
 from hashlib import sha256
 payload,patches,report=build_routed_payload(registry,edition,routes,chinese_punctuation=chinese_punctuation)
 result,reservation=reserve_payload(elf,payload,edition);b=bytearray(result)
 ph=struct.unpack_from('<I',elf,28)[0];n=struct.unpack_from('<H',elf,44)[0]
 hs=[struct.unpack_from('<8I',elf,ph+i*32) for i in range(n)];report['patches']=[]
 for address,before,after in patches:
  offsets=[o+address-v for t,o,v,p,sz,mem,fl,al in hs if t==1 and v<=address and address+len(before)<=v+sz]
  if len(offsets)!=1 or elf[offsets[0]:offsets[0]+len(before)]!=before:raise ValueError(f'Hook preimage drift at {address:#x}')
  b[offsets[0]:offsets[0]+len(after)]=after
  report['patches'].append(dict(address=address,before=before.hex(),after=after.hex()))
 report.update(reservation=reservation,payloadSha256=sha256(payload).hexdigest(),resultSha256=sha256(b).hexdigest())
 return bytes(b),report
