"""Existing-glyph CJK punctuation hooks sharing the generated metric registry.

Preserve glyph width/height; compress only matching native width and advance.
Unknown manual dimensions fall through to the existing Latin/native path.
"""
from .proportional_hooks import Asm

def metric_table(profile):
 return b''.join(bytes([m['bearing'],m['advance'],m['width'],0])for m in profile['cjkPunctuation'].values())

def select(a,profile,table):
 for i,m in enumerate(profile['cjkPunctuation'].values()):
  a.i(13,'zero','at',m['code']);a.branch(4,'t3','at',f'punct{i}')
 a.branch(4,'zero','zero','fallback')
 for i,m in enumerate(profile['cjkPunctuation'].values()):
  a.label(f'punct{i}');a.li('at',table+4*i);a.branch(4,'zero','zero','apply')

def draw(owner,end,table,profile,fallback,*,site=0x13ab58,caller=0x2253cc):
 a=Asm();saved=['at','t3','t4','t8'];a.i(9,'sp','sp',-64)
 for i,r in enumerate(saved):a.i(0x1f,'sp',r,i*16)
 a.li('at',caller);a.branch(5,'ra','at','fallback')
 a.li('at',owner+2);a.r('s4','at','t8',0x2b);a.branch(5,'t8','zero','fallback')
 a.li('at',end);a.r('s4','at','t8',0x2b);a.branch(4,'t8','zero','fallback')
 width=next(iter(profile['cjkPunctuation'].values()))['width']
 a.i(0x21,'s0','t4',12);a.i(9,'zero','at',width);a.branch(5,'t4','at','fallback')
 a.li('at',0x70000038);a.i(0x21,'at','t4',0);a.i(9,'zero','at',width);a.branch(5,'t4','at','fallback')
 a.li('at',0x70000060);a.i(0x25,'at','t3',0);select(a,profile,table)
 a.label('apply');a.i(0x24,'at','t3',0);a.i(0x21,'s0','t4',4);a.r('t4','t3','t4',0x23);a.i(0x29,'s0','t4',4)
 a.i(0x24,'at','t3',1);a.i(9,'t3','t3',-width);a.li('at',0x70000030);a.i(0x21,'at','t4',0);a.r('t4','t3','t4',0x21);a.i(0x29,'at','t4',0)
 for i,r in enumerate(saved):a.i(0x1e,'sp',r,i*16)
 a.i(9,'sp','sp',64);a.emit(0x8e230024);a.emit(0xae030014);a.jump(site+8)
 a.label('fallback')
 for i,r in enumerate(saved):a.i(0x1e,'sp',r,i*16)
 a.i(9,'sp','sp',64);a.jump(fallback)
 return a.finish()

def measure(owner,end,table,profile,fallback,*,loop=0x139b78,state=0x46e330):
 a=Asm();a.li('at',owner);a.r('a0','at','t8',0x2b);a.branch(5,'t8','zero','fallback')
 a.li('at',end-1);a.r('a0','at','t8',0x2b);a.branch(4,'t8','zero','fallback')
 width=next(iter(profile['cjkPunctuation'].values()))['width']
 # Native measurement has two modes: classified default advances (t5/t6),
 # or explicit width/step controls. Do not inspect inactive explicit fields.
 a.li('at',state);a.i(0x21,'at','t4',0x48);a.branch(4,'t4','zero','explicit')
 a.i(9,'zero','at',width);a.branch(5,'t5','at','fallback')
 # Conservatively require both native classification advances to match.
 a.branch(5,'t6','at','fallback');a.branch(4,'zero','zero','lookup')
 a.label('explicit')
 for field in [0x14,0x18]:
  a.li('at',state);a.i(0x21,'at','t4',field);a.i(9,'zero','at',width);a.branch(5,'t4','at','fallback')
 a.label('lookup')
 a.i(0x24,'a0','t3',0);a.r('zero','t3','t3',0,8);a.i(0x24,'a0','t4',1);a.r('t3','t4','t3',0x25)
 select(a,profile,table);a.label('apply');a.i(0x24,'at','t4',1);a.r('v0','t4','v0',0x21);a.i(9,'a0','a0',2);a.jump(loop)
 a.label('fallback');a.jump(fallback);return a.finish()
