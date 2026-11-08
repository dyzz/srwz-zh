"""Compact ISO candidate: shared draw/measure code and GS baseline translation.

Routes are explicit audited owners. The per-call selector has no calls/yields;
selected globals are consumed before returning to native code. No ISO growth.
"""
import struct
from hashlib import sha256
from .proportional_hooks import Asm,draw_hook,measure_hook,cjk_runtime_table,keyword_underline_hooks,metric_selection_subroutine
from .proportional_metrics import runtime_table,CJK_NATIVE
from .proportional_payload import LAYOUTS,reserve_payload
from .proportional_routes import SITES

ROUTES={
 'original':[
  dict(name='story',scene='story',draw=(0x1fff000,0x2000000),measure=(0xf06293,0xf0648c),caller=0x2253cc,dynamic=True),
  dict(name='scroll',scene='main_scroll',draw=(0x111c900,0x111d000),measure=(0x111c900,0x111d000),caller=0x2253cc),
 ],
 'sp':[
  dict(name='library_character',scene='library_character',draw=(0x62ec60,0x62ed60),measure=(0xd6d8c0,0xd6dac4),caller=0x22a33c),
  dict(name='synopsis',scene='sp_flow',draw=(0x8093e0,0x80956a),measure=(0x8093e0,0x80956a),caller=0x1ab058),
 ],
}

def words(*v):return struct.pack('<'+'I'*len(v),*v)

def vertex_hook(sidecar,offsets,displaced,return_site):
 a=Asm();saved=['at','t3','t4'];a.i(9,'sp','sp',-48)
 for n,r in enumerate(saved):a.i(0x1f,'sp',r,n*16)
 a.i(12,'a3','t4',0x3fff);a.r('zero','t4','t4',2,5)
 a.li('at',sidecar);a.r('at','t4','at',0x21);a.i(0x20,'at','t3',0)
 for offset in offsets:
  a.i(0x25,'a0','t4',offset);a.r('t4','t3','t4',0x21);a.i(0x29,'a0','t4',offset)
 for n,r in enumerate(saved):a.i(0x1e,'sp',r,n*16)
 a.i(9,'sp','sp',48)
 for word in displaced:a.emit(word)
 a.jump(return_site);return a.finish()

def selector(routes,targets,globals_,sidecar,native,generic,kind):
 a=Asm();a.i(9,'sp','sp',-32);a.i(0x1f,'sp','at',0);a.i(0x1f,'sp','t8',16)
 source='s4' if kind=='draw' else 'a0'
 if kind=='draw':
  a.i(12,'s0','t8',0x3fff);a.r('zero','t8','t8',2,5);a.li('at',sidecar)
  a.r('at','t8','at',0x21);a.i(0x28,'at','zero',0)
 def leave(target):
  a.i(0x1e,'sp','at',0);a.i(0x1e,'sp','t8',16);a.i(9,'sp','sp',32);a.jump(target)
 for i,(route,(table,cjk,width)) in enumerate(zip(routes,targets)):
  next_=f'next{i}';lo,hi=route[kind]
  if kind=='draw':
   a.li('at',route['caller']);a.branch(5,'ra','at',next_)
   for field,size in zip((12,14),CJK_NATIVE[route['scene']]):
    a.i(0x21,'s0','t8',field);a.i(9,'zero','at',size);a.branch(5,'t8','at',next_)
  if kind=='draw' and route.get('dynamic'):
   a.li('at',0x2000000);a.r('s6','at','t8',0x2b);a.branch(4,'t8','zero',next_)
   a.r('s5','s6','t8',0x2b);a.branch(4,'t8','zero',next_)
   a.i(9,'s5','at',2);a.r(source,'at','t8',0x2b);a.branch(5,'t8','zero',next_)
   a.i(9,'s6','at',1);a.r(source,'at','t8',0x2b);a.branch(4,'t8','zero',next_)
   a.li('at',globals_);a.i(0x2b,'at','s5',0);a.i(9,'s6','t8',1);a.i(0x2b,'at','t8',4)
  else:
   a.li('at',lo+(2 if kind=='draw' else 0));a.r(source,'at','t8',0x2b);a.branch(5,'t8','zero',next_)
   a.li('at',hi-(1 if kind=='measure' else 0));a.r(source,'at','t8',0x2b);a.branch(4,'t8','zero',next_)
   a.li('at',globals_)
   for offset,value in [(0,lo),(4,hi)]:a.li('t8',value);a.i(0x2b,'at','t8',offset)
  for offset,value in ([(8,table),(12,cjk),(16,width)] if kind=='draw' else [(8,table),(12,cjk)]):a.li('t8',value);a.i(0x2b,'at','t8',offset)
  leave(generic);a.label(next_)
 leave(native);return a.finish()

def build_payload(registry,edition,*,routes=None,shared_selection=False,scene_dispatch=False):
 if scene_dispatch:
  from .proportional_scene_dispatch import SCENES,source_entry,style_selector
  routes=[dict(name=s,scene=s) for s in SCENES[edition]];shared_selection=True
 routes=ROUTES[edition] if routes is None else routes
 keyword=edition in ('original','best') or scene_dispatch
 if edition=='best' and not scene_dispatch:raise ValueError('Best requires native-entry scene dispatch')
 text_state={'original':0x46e330,'best':0x46eb30,'sp':0x4ed5b0}[edition]
 c=LAYOUTS[edition];base=c['base'];limit=c['capacity']-(0x240 if keyword else 0x220)
 sidecar=base+limit;globals_=sidecar+512
 site,loop,epilogue=SITES[edition];delta=site-0x13ab58
 blob=bytearray();sections=[]
 def add(name,data):
  blob.extend(bytes((-len(blob))%4));address=base+len(blob);blob.extend(data)
  sections.append(dict(name=name,address=address,size=len(data)))
  if len(blob)>limit:raise ValueError(f'{edition} payload exceeds code/data limit: {len(blob)}/{limit} at {name}')
  return address
 a=Asm();a.emit(0x8e230024);a.emit(0xae030014);a.jump(site+8);native_draw=add('native_draw',a.finish())
 a=Asm();a.i(0x24,'a0','t3',0);a.branch(4,'t3','zero','end');a.jump(loop+8);a.label('end');a.jump(epilogue);native_measure=add('native_measure',a.finish())
 targets=[];metric_cache={};cjk_cache={}
 for r in routes:
  profile=registry['profiles'][r['scene']]
  if scene_dispatch:
   import copy
   normalized=copy.deepcopy(profile)
   for m in [*normalized['glyphs'].values(),*normalized['punctuation'].values(),normalized['space']]:
    m.update(height=0,yOffset=0,baselineResidual16=0)
   data=runtime_table(normalized)
   if data not in metric_cache:metric_cache[data]=add(r['name']+'_metrics',data)
   cjk=cjk_runtime_table(profile)
   if cjk not in cjk_cache:cjk_cache[cjk]=add(r['name']+'_cjk',cjk)
   letter,digit=profile['glyphs']['A'],profile['glyphs']['3']
   geometry=bytes([letter['height'],digit['height'],letter['yOffset']&255,letter['baselineResidual16']&255,digit['baselineResidual16']&255])
   targets.append((metric_cache[data],cjk_cache[cjk],letter['width'],add(r['name']+'_geometry',geometry)))
  else:
   targets.append((add(r['name']+'_metrics',runtime_table(profile,include_residuals=True)),add(r['name']+'_cjk',cjk_runtime_table(profile)),profile['glyphs']['A']['width']))
 bound=lambda offset:('memory',globals_+offset)
 selection=add('metric_selection',metric_selection_subroutine(bound(0),bound(4),bound(8))) if shared_selection else None
 generic_draw=add('shared_draw',draw_hook(bound(0),bound(4),bound(8),bound(16),site=site,cjk_table=bound(12),spaced_slash=True,residual_sidecar=sidecar,selection_subroutine=selection,geometry=bound(20) if scene_dispatch else None))
 generic_measure=add('shared_measure',measure_hook(bound(0),bound(4),bound(8),site=loop,epilogue=epilogue,cjk_table=bound(12),state=text_state,spaced_slash=True,selection_subroutine=selection))
 select=style_selector if scene_dispatch else selector
 options=dict(state=text_state) if scene_dispatch else {}
 if scene_dispatch:
  descriptors=b''.join(words(*CJK_NATIVE[r['scene']],*target) for r,target in zip(routes,targets))+bytes(24)
  options['descriptors']=add('scene_descriptors',descriptors)
 draw_entry=add('draw_routes',select(routes,targets,globals_,sidecar,native_draw,generic_draw,'draw',**options))
 measure_entry=add('measure_routes',select(routes,targets,globals_,sidecar,native_measure,generic_measure,'measure',**options))
 patches=[]
 if scene_dispatch:
  for name,entry,displaced in [('draw_source',0x13a290+delta,(0x27bdffa0,0x3c010047 if edition in ('original','best') else 0x3c01004f)),('measure_source',0x139b00+delta,(0x27bdffb0,0x0000102d))]:
   at=add(name,source_entry(globals_,entry+8,displaced))
   patches.append((entry,words(*displaced),words(0x08000000|(at>>2),0)))
 if keyword:
  # Scratch is separate from selector globals; outline advance remains exact.
  kw_options={'original':{},'best':dict(state=0x46eb40,underline_source=0x5a5250,copy_fn=0x1a1530,draw_site=site),'sp':dict(state=0x4ed5c0,underline_source=0x62ee90,copy_fn=0x1a5640,draw_site=site)}[edition]
  copy,restore,_=keyword_underline_hooks(globals_+32,draw_entry,**kw_options)
  copy_at=add('underline_copy',copy);restore_at=add('underline_restore',restore)
  _,_,dispatch=keyword_underline_hooks(globals_+32,draw_entry,**kw_options)
  kw=add('underline_dispatch',dispatch)
  # Clear the sidecar even when the underline dispatcher bypasses text routing.
  a=Asm();a.i(9,'sp','sp',-32);a.i(0x1f,'sp','at',0);a.i(0x1f,'sp','t8',16)
  a.i(12,'s0','t8',0x3fff);a.r('zero','t8','t8',2,5);a.li('at',sidecar);a.r('at','t8','at',0x21);a.i(0x28,'at','zero',0)
  a.i(0x1e,'sp','at',0);a.i(0x1e,'sp','t8',16);a.i(9,'sp','sp',32);a.jump(kw)
  draw_entry=add('draw_entry',a.finish())
  copy_site,restore_site,width_site={'original':(0x2215f4,0x221628,0x22163c),'best':(0x2219b4,0x2219e8,0x2219fc),'sp':(0x22658c,0x2265c0,0x2265d4)}[edition]
  copy_fn=kw_options.get('copy_fn',0x1a1190)
  width_code={'original':(0x3c010047,0x8423e340,0x0060a02d),'best':(0x3c010047,0x8423eb40,0x0060a02d),'sp':(0x3c01004f,0x8423d5c0,0x0060a02d)}[edition]
  patches.extend([(copy_site,words(0x0c000000|(copy_fn>>2)),words(0x0c000000|(copy_at>>2))),
   (restore_site,words(0x26020002,0x02429021),words(0x0c000000|(restore_at>>2),0)),
   (width_site,words(0x00022042,0x00641818,0x0283a021),words(*width_code))])
 simple_site=0x13b368+delta;outline_site=0x13af44+delta
 for name,ps,offsets,displaced in [('sprite',simple_site,(-14,2),(0x24840008,0x80e8001c)),('outline',outline_site,(-46,-30,-14,2),(0x80e8001c,0x24840008))]:
  at=add(name+'_baseline',vertex_hook(sidecar,offsets,displaced,ps+8));patches.append((ps,words(*displaced),words(0x08000000|(at>>2),0)))
 patches.extend([(site,words(0x8e230024,0xae030014),words(0x08000000|(draw_entry>>2),0)),(loop,bytes.fromhex('00008b9062006011'),words(0x08000000|(measure_entry>>2),0))])
 code_size=len(blob);blob.extend(bytes(c['capacity']-len(blob)))
 sections.extend([dict(name='baseline_sidecar',address=sidecar,size=512),dict(name='selector_globals',address=globals_,size=64 if keyword else 32)])
 return bytes(blob),patches,dict(edition=edition,base=base,codeBytes=code_size,payloadBytes=len(blob),sections=sections,routes=routes,sharedSelection=shared_selection,sceneDispatch=scene_dispatch,metricsSchema=registry['schemaVersion'],fontSha256=registry['fontSha256'],scope='Native-entry bounded scene geometry dispatch' if scene_dispatch else 'Integrated candidate with dynamic ordinary dialogue and explicit audited other owners')

def install(elf,registry,edition,**options):
 payload,patches,report=build_payload(registry,edition,**options)
 result,reservation=reserve_payload(elf,payload,edition);b=bytearray(result)
 ph=struct.unpack_from('<I',elf,28)[0];n=struct.unpack_from('<H',elf,44)[0]
 hs=[struct.unpack_from('<8I',elf,ph+i*32) for i in range(n)];report['patches']=[]
 for address,before,after in patches:
  offsets=[o+address-v for t,o,v,p,sz,mem,fl,al in hs if t==1 and v<=address and address+len(before)<=v+sz]
  if len(offsets)!=1 or elf[offsets[0]:offsets[0]+len(before)]!=before:raise ValueError(f'Hook preimage drift at {address:#x}')
  b[offsets[0]:offsets[0]+len(after)]=after;report['patches'].append(dict(address=address,before=before.hex(),after=after.hex()))
 report.update(reservation=reservation,payloadSha256=sha256(payload).hexdigest(),resultSha256=sha256(b).hexdigest())
 return bytes(b),report
