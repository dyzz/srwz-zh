"""Scene-sized dispatch, with source bounds captured at native text entry.

No resource-instance addresses. Known body geometry selects one shared profile;
unknown UI sizes retain native behavior. Source controls are skipped as pairs,
newlines as bytes. Invalid or overlong buffers fail closed.
"""
from .proportional_hooks import Asm
from .proportional_metrics import CJK_NATIVE

SCENES={
 'original':('story','battle','main_flow','main_scroll','library_robot','weapon','weapon_main'),
 'best':('story','battle','main_flow','main_scroll','library_robot','weapon','weapon_main'),
 'sp':('story','battle','sp_flow','sp_scroll','library_robot','weapon'),
}

def source_entry(globals_,return_site,displaced):
 a=Asm();saved=['at','t3','t4','t8'];a.i(9,'sp','sp',-64)
 for n,r in enumerate(saved):a.i(0x1f,'sp',r,n*16)
 a.li('at',globals_);a.i(0x2b,'at','zero',0);a.i(0x2b,'at','zero',4)
 a.i(15,'zero','at',0x10);a.r('a0','at','t8',0x2b);a.branch(5,'t8','zero','restore')
 a.i(15,'zero','at',0x200);a.r('a0','at','t8',0x2b);a.branch(4,'t8','zero','restore')
 a.i(9,'a0','t3',0);a.i(15,'zero','t4',1);a.r('a0','t4','t4',0x21)
 # Clamp the scan to physical RAM, including the near-top dialogue scratch buffer.
 a.r('at','t4','t8',0x2b);a.r('at','t8','t4',0x0b)
 a.label('scan');a.r('t3','t4','t8',0x2b);a.branch(4,'t8','zero','restore')
 a.i(0x24,'t3','t8',0);a.branch(4,'t8','zero','found')
 a.i(9,'zero','at',10);a.branch(4,'t8','at','newline')
 a.i(9,'t3','t3',1)
 a.label('newline');a.i(9,'t3','t3',1);a.branch(4,'zero','zero','scan')
 a.label('found');a.li('at',globals_);a.i(0x2b,'at','a0',0)
 a.i(9,'t3','t3',1);a.i(0x2b,'at','t3',4)
 a.label('restore')
 for n,r in enumerate(saved):a.i(0x1e,'sp',r,n*16)
 a.i(9,'sp','sp',64)
 for w in displaced:a.emit(w)
 a.jump(return_site);return a.finish()

def style_selector(routes,targets,globals_,sidecar,native,generic,kind,*,state):
 a=Asm();saved=['at','t3','t4','t8'];a.i(9,'sp','sp',-64)
 for n,r in enumerate(saved):a.i(0x1f,'sp',r,n*16)
 if kind=='draw':
  a.i(12,'s0','t8',0x3fff);a.r('zero','t8','t8',2,5);a.li('at',sidecar)
  a.r('at','t8','at',0x21);a.i(0x28,'at','zero',0)
  a.li('at',0x70000068);a.i(0x21,'at','t8',0)
  a.branch(4,'t8','zero','explicit')
  a.li('at',state);a.i(0x21,'at','t3',0x38);a.i(0x21,'at','t4',0x3a)
  a.branch(4,'zero','zero','select')
  a.label('explicit');a.i(0x21,'s0','t3',12);a.i(0x21,'s0','t4',14)
 else:
  a.li('at',state);a.i(0x21,'at','t8',0x48)
  a.branch(4,'t8','zero','explicit')
  a.i(0x21,'at','t3',0x38);a.branch(4,'zero','zero','select')
  a.label('explicit');a.i(0x21,'at','t3',0x14)
 a.label('select')
 def leave(target):
  for n,r in enumerate(saved):a.i(0x1e,'sp',r,n*16)
  a.i(9,'sp','sp',64);a.jump(target)
 seen=set()
 for i,(r,(table,cjk,width,geometry)) in enumerate(zip(routes,targets)):
  w,h=CJK_NATIVE[r['scene']]
  if kind=='measure' and w in seen:continue
  seen.add(w);next_=f'next{i}'
  a.i(9,'zero','at',w);a.branch(5,'t3','at',next_)
  if kind=='draw':a.i(9,'zero','at',h);a.branch(5,'t4','at',next_)
  a.li('at',globals_)
  values=[(8,table),(12,cjk)]
  if kind=='draw':values.extend([(16,width),(20,geometry)])
  for offset,value in values:
   if offset==16:a.i(9,'zero','t8',value)
   else:
    assert -32768<=value-globals_<32768
    a.i(9,'at','t8',value-globals_)
   a.i(0x2b,'at','t8',offset)
  a.branch(4,'zero','zero','selected');a.label(next_)
 leave(native);a.label('selected');leave(generic);return a.finish()
