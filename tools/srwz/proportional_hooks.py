"""Owner-scoped EE hooks for isolated tag-free Latin runtime candidates.

Hook only the measure loop, retaining native CJK classification, control state,
return semantics and caller ABI. Unselected source ranges execute native code.
"""
import struct
from .proportional_metrics import contextual_slots, METRIC_BYTES
R={name:i for i,name in enumerate('zero at v0 v1 a0 a1 a2 a3 t0 t1 t2 t3 t4 t5 t6 t7 s0 s1 s2 s3 s4 s5 s6 s7 t8 t9 k0 k1 gp sp fp ra'.split())}
class Asm:
    def __init__(self):self.words=[];self.labels={};self.fixups=[]
    def emit(self,w):self.words.append(w)
    def i(self,op,rs,rt,v):self.emit(op<<26|R[rs]<<21|R[rt]<<16|(v&65535))
    def r(self,rs,rt,rd,fn,shift=0):self.emit(R[rs]<<21|R[rt]<<16|R[rd]<<11|shift<<6|fn)
    def li(self,reg,v):self.i(15,'zero',reg,v>>16);self.i(13,reg,reg,v&65535)
    def label(self,name):self.labels[name]=len(self.words)
    def branch(self,op,rs,rt,label):self.fixups.append((len(self.words),label));self.i(op,rs,rt,0);self.emit(0)
    def jump(self,address):self.emit(0x08000000|(address>>2));self.emit(0)
    def finish(self):
        for at,label in self.fixups:
            offset=self.labels[label]-at-1
            if not -32768<=offset<32768:raise ValueError('Branch out of range')
            self.words[at]|=offset&65535
        return struct.pack('<'+'I'*len(self.words),*self.words)

# Metric record size the generated code indexes: 4 bytes (bearing, advance, height,
# offset/enable) or the compact 2 bytes (bearing, advance; advance 0 = absent) used with
# scene geometry dispatch, where height and offset come from the scene record.
_RECORD_BYTES=4

class compact_records:
    """Generate hooks for two-byte metric records inside the ``with`` block."""
    def __enter__(self):
        global _RECORD_BYTES
        self.previous=_RECORD_BYTES;_RECORD_BYTES=2
    def __exit__(self,*_):
        global _RECORD_BYTES
        _RECORD_BYTES=self.previous

def slot_offset(offset):
    """Byte offset of a metric slot given its offset in the four-byte layout."""
    return offset*_RECORD_BYTES//4

def table_address(a,reg,value,delta=0):
    if isinstance(value,tuple):
        kind,address=value
        if kind!='memory':raise ValueError('Unsupported indirect address')
        a.i(15,'zero',reg,(address+0x8000)>>16);a.i(0x23,reg,reg,address)
        if delta:a.i(9,reg,reg,delta)
    else:a.li(reg,value+delta)

def cjk_runtime_table(profile, *, compact_sentinel=False):
    """Six-byte code/metric records, followed by a zero-code sentinel.

    The continuation indent is one more record: a blank glyph with the opener's advance.
    """
    records=[*profile['cjkPunctuation'].values()]
    if 'continuationIndent' in profile:records.append(profile['continuationIndent'])
    return b''.join(struct.pack('<H4B',m['code'],m['bearing'],m['advance'],m['width'],0)
                    for m in records)+bytes(2 if compact_sentinel else 6)

def cjk_lookup(a,table):
    # t3 is the encoded character; at/t4/t8 are caller scratch registers.
    table_address(a,'t8',table);a.label('cjk_scan')
    a.i(0x25,'t8','t4',0);a.branch(4,'t4','zero','latin')
    a.branch(4,'t3','t4','cjk_found');a.i(9,'t8','t8',6)
    a.branch(4,'zero','zero','cjk_scan');a.label('latin')


def measure_hook(owner,end,table,site=0x139b78,epilogue=0x139d08,*,cjk_table=None,state=0x46e330,spaced_slash=False,selection_subroutine=None):
    """At loop head a0=current source, a1=full/half, v0=advance sum.

    at,t3,t4,t8 are scratch at this point. Other registers (including v1 and
    font classification constants) remain intact. Both source and metric table
    are bounds checked. All branches have explicit neutral delay slots.
    """
    a=Asm()
    a.i(0x24,'a0','t3',0);a.branch(4,'t3','zero','end')
    load_bound(a,owner);a.r('a0','at','t8',0x2b);a.branch(5,'t8','zero','original')
    load_bound(a,end,-1);a.r('a0','at','t8',0x2b);a.branch(4,'t8','zero','original')
    # Height and line-step are controls, never visible two-byte glyphs.
    for control in (0x33,0x35):
        a.i(9,'zero','at',control);a.branch(4,'t3','at','skip')
    a.r('zero','t3','t3',0,8);a.i(0x24,'a0','t4',1);a.r('t3','t4','t3',0x25)
    if cjk_table is not None:cjk_lookup(a,cjk_table)
    if selection_subroutine is None:
        select_metric(a,table,'a0',0,owner,end,'original','add',spaced_slash=spaced_slash)
    else:
        call_selection(a,selection_subroutine,'a0',0,'original','add')
    if cjk_table is not None:
        a.label('cjk_found');a.i(0x24,'t8','t4',4)
        a.li('at',state);a.i(0x21,'at','t3',0x48);a.branch(4,'t3','zero','cjk_explicit')
        # Every CJK table code is outside the native half-width classification
        # ranges. Its automatic advance is t5; unrelated Latin t6 may differ.
        a.branch(5,'t5','t4','original')
        a.branch(4,'zero','zero','cjk_add')
        a.label('cjk_explicit')
        for field in (0x14,0x18):
            a.i(0x21,'at','t3',field);a.branch(5,'t3','t4','original')
        a.label('cjk_add');a.i(9,'t8','at',2)
    a.label('add');a.i(0x24,'at','t4',1);a.r('v0','t4','v0',0x21)
    a.label('skip');a.i(9,'a0','a0',2);a.jump(site)
    a.label('original');a.i(0x24,'a0','t3',0);a.jump(site+8)
    a.label('end');a.jump(epilogue)
    return a.finish()

def lookup(a,table,fallback):
    a.i(13,'zero','at',0x824f);a.r('t3','at','t4',0x23)
    a.i(0xb,'t4','t8',76);a.branch(4,'t8','zero',fallback)
    a.r('zero','t4','t4',0,2 if _RECORD_BYTES==4 else 1);table_address(a,'at',table);a.r('at','t4','at',0x21)
    a.i(0x24,'at','t8',3 if _RECORD_BYTES==4 else 1);a.branch(4,'t8','zero',fallback)

def load_bound(a,bound,delta=0):
    """An absolute owner address or a verified preserved-register bound."""
    if isinstance(bound,tuple):
        register,bias=bound
        if register=='memory':
            table_address(a,'at',bound,delta);return
        if register not in ('s5','s6'):raise ValueError('Unaudited dynamic source register')
        a.i(9,register,'at',bias+delta)
    else:a.li('at',bound+delta)

def draw_hook(owner,end,table,width,site=0x13ab58,caller=None,*,cjk_table=None,native_size=None,spaced_slash=False,residual_sidecar=None,selection_subroutine=None,geometry=None):
    """Override Latin cell dimensions without requiring source dimension tags."""
    a=Asm();saved=['at','t3','t4','t8'];a.i(9,'sp','sp',-64)
    for n,r in enumerate(saved):a.i(0x1f,'sp',r,n*16)
    if caller is not None:
        a.li('at',caller);a.branch(5,'ra','at','restore')
    if (isinstance(owner,tuple) and owner[0]!='memory') or (isinstance(end,tuple) and end[0]!='memory'):
        if (owner,end)!=(('s5',0),('s6',1)) or caller is None or native_size is None:
            raise ValueError('Dynamic bounds require the audited string ABI, caller and native size')
        # s5 is the string start, s6 the terminating NUL in this caller only.
        a.li('at',0x2000000);a.r('s6','at','t8',0x2b);a.branch(4,'t8','zero','restore')
        a.r('s5','s6','t8',0x2b);a.branch(4,'t8','zero','restore')
    if native_size is not None:
        for field,size in zip((12,14),native_size):
            a.i(0x21,'s0','t4',field);a.i(9,'zero','at',size);a.branch(5,'t4','at','restore')
    load_bound(a,owner,2);a.r('s4','at','t8',0x2b);a.branch(5,'t8','zero','restore')
    load_bound(a,end);a.r('s4','at','t8',0x2b);a.branch(4,'t8','zero','restore')
    a.li('at',0x70000060);a.i(0x25,'at','t3',0)
    if cjk_table is not None:cjk_lookup(a,cjk_table)
    if selection_subroutine is None:
        select_metric(a,table,'s4',-2,owner,end,'restore','apply',spaced_slash=spaced_slash)
    else:
        call_selection(a,selection_subroutine,'s4',-2,'restore','apply')
    if cjk_table is not None:
        a.label('cjk_found');a.i(0x24,'t8','t3',4)
        a.i(0x21,'s0','t4',12);a.branch(5,'t3','t4','restore')
        a.li('at',0x70000038);a.i(0x21,'at','t4',0);a.branch(5,'t3','t4','restore')
        a.i(9,'t8','at',2);a.branch(4,'zero','zero','bearing')
    a.label('apply')
    if geometry is not None:
        if residual_sidecar is None:raise ValueError('Scene geometry requires baseline sidecar')
        a.li('t8',0x70000060);a.i(0x25,'t8','t4',0)
        # Only the stock space takes the space cell; the release space alias is a blank
        # glyph, so letter geometry draws it identically and keeps the SP cave in budget.
        a.i(13,'zero','t8',0x8140);a.branch(5,'t4','t8','visible_geometry')
        table_address(a,'t3',geometry);a.i(0x24,'t3','t4',1);a.i(0x29,'s0','t4',14)
        table_address(a,'t3',width);a.i(0x29,'s0','t3',12)
        a.branch(4,'zero','zero','bearing')
        a.label('visible_geometry')
        table_address(a,'t3',geometry)
        a.i(0x20,'t3','t4',2);a.i(0x21,'s0','t8',6)
        a.r('t8','t4','t8',0x21);a.i(0x29,'s0','t8',6)
        a.li('t8',0x70000060);a.i(0x25,'t8','t4',0)
        a.i(13,'zero','t8',0x824f);a.r('t4','t8','t4',0x23);a.i(0xb,'t4','t4',10)
        a.branch(4,'t4','zero','letter_geometry')
        a.i(0x24,'t3','t4',1);a.i(0x29,'s0','t4',14)
        a.i(0x20,'t3','t3',4);a.branch(4,'zero','zero','store_residual')
        a.label('letter_geometry');a.i(0x24,'t3','t4',0)
        a.i(0x29,'s0','t4',14);a.i(0x20,'t3','t3',3)
        a.label('store_residual');a.i(12,'s0','t4',0x3fff)
        a.r('zero','t4','t4',2,5);a.li('t8',residual_sidecar)
        a.r('t8','t4','t8',0x21);a.i(0x28,'t8','t3',0)
        table_address(a,'t3',width);a.i(0x29,'s0','t3',12)
        a.branch(4,'zero','zero','bearing')
    if geometry is None:
        # Reached only without scene geometry: both geometry branches jump to 'bearing'.
        if residual_sidecar is not None:
            table_address(a,'t3',table)
            a.r('at','t3','t4',0x23);a.r('zero','t4','t4',2,2)
            a.r('t3','t4','t3',0x21);a.i(0x20,'t3','t3',METRIC_BYTES)
            a.i(12,'s0','t4',0x3fff);a.r('zero','t4','t4',2,5)
            a.li('t8',residual_sidecar);a.r('t8','t4','t8',0x21);a.i(0x28,'t8','t3',0)
        if isinstance(width,tuple):table_address(a,'t3',width)
        else:a.i(9,'zero','t3',width)
        a.i(0x29,'s0','t3',12)
        a.i(0x24,'at','t3',2);a.i(0x29,'s0','t3',14)
        # Decode the signed seven-bit baseline offset, preserving glyph shape.
        a.i(0x20,'at','t3',3);a.r('zero','t3','t3',3,1)
        a.i(0x21,'s0','t4',6);a.r('t4','t3','t4',0x21);a.i(0x29,'s0','t4',6)
    a.label('bearing')
    a.i(0x24,'at','t3',0);a.i(0x21,'s0','t4',4);a.r('t4','t3','t4',0x23);a.i(0x29,'s0','t4',4)
    a.i(0x24,'at','t3',1);a.li('at',0x70000000)
    a.i(0x21,'at','t4',0x38);a.r('t3','t4','t3',0x23)
    a.i(0x21,'at','t4',0x30);a.r('t4','t3','t4',0x21);a.i(0x29,'at','t4',0x30)
    a.label('restore')
    for n,r in enumerate(saved):a.i(0x1e,'sp',r,n*16)
    a.i(9,'sp','sp',64);a.emit(0x8e230024);a.emit(0xae030014);a.jump(site+8)
    return a.finish()


def call_selection(a,address,source,offset,fallback,done):
    """Call the shared selector, preserving full EE ra/t9 (including fallback)."""
    a.i(9,'sp','sp',-32)
    a.i(0x1f,'sp','ra',0);a.i(0x1f,'sp','t9',16)
    a.i(9,source,'t9',offset)
    a.emit(0x0c000000|(address>>2));a.emit(0)
    a.i(0x1e,'sp','ra',0);a.i(0x1e,'sp','t9',16)
    a.i(9,'sp','sp',32)
    a.branch(4,'at','zero',fallback);a.branch(4,'zero','zero',done)

def metric_selection_subroutine(owner,end,table,*,spaced_slash=True):
    """t9=current source, t3=code; return at=metric or zero, ra/t9 intact."""
    a=Asm()
    select_metric(a,table,'t9',0,owner,end,'absent','selected',spaced_slash=spaced_slash)
    a.label('absent');a.i(9,'zero','at',0)
    a.label('selected');a.r('ra','zero','zero',8);a.emit(0)
    return a.finish()

def select_metric(a,table,source,offset,owner,end,fallback,done,*,spaced_slash=False):
    """Alnums unconditional; spaces and identifier punctuation between alnums.

    source+offset points at the current character. Same emitted selection logic
    is used for drawing and native measurement.
    """
    slots=contextual_slots()
    if spaced_slash:
        slash_code,slash_slot=slots[-1]
        a.i(13,'zero','at',slash_code);a.branch(4,'t3','at','slash_current')
        # Spaced-slash forms ("A / B") occur once, in a menu that stores 0x8140; the
        # release space alias is matched only by the plain word-space path below.
        a.i(13,'zero','at',0x8140);a.branch(4,'t3','at','space_current')
        a.branch(4,'zero','zero','spaced_done')
        def read_neighbor(delta,fail):
            at=offset+delta
            load_bound(a,owner,-at);a.r(source,'at','t8',0x2b);a.branch(5,'t8','zero',fail)
            load_bound(a,end,-1-at);a.r(source,'at','t8',0x2b);a.branch(4,'t8','zero',fail)
            a.i(0x24,source,'t3',at);a.r('zero','t3','t3',0,8)
            a.i(0x24,source,'t4',at+1);a.r('t3','t4','t3',0x25)
        def optional_space(delta,label,fail):
            read_neighbor(delta,fail)
            a.i(13,'zero','at',0x8140);a.branch(5,'t3','at',label)
            read_neighbor(delta+(2 if delta>0 else -2),fail)
            a.label(label);lookup(a,table,fail)
        a.label('slash_current')
        for delta,label in [(-2,'slash_left'),(2,'slash_right')]:
            optional_space(delta,label,'spaced_done')
        table_address(a,'at',table,slot_offset(slash_slot));a.branch(4,'zero','zero',done)
        a.label('space_current')
        for direction,label,fail in [(1,'space_right','space_left_try'),(-1,'space_left','spaced_done')]:
            read_neighbor(-2*direction,fail);lookup(a,table,fail)
            read_neighbor(2*direction,fail)
            a.i(13,'zero','at',slash_code);a.branch(5,'t3','at',fail)
            optional_space(4*direction,label,fail)
            table_address(a,'at',table,slot_offset(304));a.branch(4,'zero','zero',done)
            if direction==1:a.label(fail)
        a.label('spaced_done')
        a.i(0x24,source,'t3',offset);a.r('zero','t3','t3',0,8)
        a.i(0x24,source,'t4',offset+1);a.r('t3','t4','t3',0x25)
    for code,slot in slots:
        a.i(13,'zero','at',code);a.branch(4,'t3','at','context')
    lookup(a,table,fallback);a.branch(4,'zero','zero',done)
    a.label('context')
    load_bound(a,owner,2-offset);a.r(source,'at','t8',0x2b);a.branch(5,'t8','zero',fallback)
    load_bound(a,end,-3-offset);a.r(source,'at','t8',0x2b);a.branch(4,'t8','zero',fallback)
    for delta in (-2,2):
        a.i(0x24,source,'t3',offset+delta);a.r('zero','t3','t3',0,8)
        a.i(0x24,source,'t4',offset+delta+1);a.r('t3','t4','t3',0x25)
        lookup(a,table,fallback)
    a.i(0x24,source,'t3',offset);a.r('zero','t3','t3',0,8)
    a.i(0x24,source,'t4',offset+1);a.r('t3','t4','t3',0x25)
    # Only codes listed in slots reach 'context', so a code that matches no punctuation
    # slot is one of the space codes: fall through to the shared space record.
    space_slot=slots[0][1]
    for code,slot in slots:
        if slot!=space_slot:
            a.i(13,'zero','at',code);a.branch(4,'t3','at',f'slot{slot}')
    a.label(f'slot{space_slot}');table_address(a,'at',table,slot_offset(space_slot));a.branch(4,'zero','zero',done)
    for slot in dict.fromkeys(slot for _,slot in slots if slot!=space_slot):
        a.label(f'slot{slot}');table_address(a,'at',table,slot_offset(slot));a.branch(4,'zero','zero',done)


def keyword_underline_hooks(scratch, draw_fallback, *, state=0x46e340,
                            underline_source=0x5a4a50, copy_fn=0x1a1190,
                            draw_site=0x13ab58):
    """RAM candidate: reuse one existing underscore stretched to true term width.

    Capture end X before underline rendering, then restore it for the segment
    consumer. No private glyph, font mutation or character-count approximation.
    Returns copy-call stub, post-draw stub and draw dispatcher. Call-site ABI
    permits at/t0/t1 scratch in the copy stub; draw preserves full EE registers.
    """
    a=Asm();a.li('at',state);a.i(0x21,'at','t0',0)
    a.li('at',scratch);a.i(0x29,'at','t0',0)
    a.r('t0','s4','t1',0x23);a.i(0x29,'at','t1',2)
    a.i(9,'zero','a2',2);a.i(0x29,'a0','zero',2);a.jump(copy_fn)
    copy=a.finish()
    a=Asm();a.li('at',scratch);a.i(0x21,'at','t9',0)
    a.li('at',state);a.i(0x29,'at','t9',0)
    a.emit(0x26020002);a.emit(0x02429021);a.r('ra','zero','zero',8);a.emit(0)
    restore=a.finish()
    a=Asm();saved=['at','t3','t4','t8'];a.i(9,'sp','sp',-64)
    for n,r in enumerate(saved):a.i(0x1f,'sp',r,n*16)
    a.li('at',underline_source+2);a.branch(5,'s4','at','fallback')
    a.li('at',scratch);a.i(0x21,'at','t3',2);a.i(0x29,'s0','t3',12)
    a.li('at',0x70000000);a.i(0x21,'at','t4',0x38)
    a.r('t3','t4','t3',0x23);a.i(0x21,'at','t4',0x30)
    a.r('t4','t3','t4',0x21);a.i(0x29,'at','t4',0x30)
    for n,r in enumerate(saved):a.i(0x1e,'sp',r,n*16)
    a.i(9,'sp','sp',64);a.emit(0x8e230024);a.emit(0xae030014);a.jump(draw_site+8)
    a.label('fallback')
    for n,r in enumerate(saved):a.i(0x1e,'sp',r,n*16)
    a.i(9,'sp','sp',64);a.jump(draw_fallback)
    return copy,restore,a.finish()


def glyph_bank_hook(globals_,descriptors,state,site,*,bank_base,punctuation,dynamic_path):
    """Draw Latin text from the HarmonyOS glyph bank in the proportional scenes.

    Hooked where the native draw loop has resolved the glyph index of the current
    character (scratch 0x70000062, about to be published at 0x70000000). When the
    character is a Latin letter, digit or identifier punctuation, the string is one
    the proportional hooks own and the cell size names a proportional scene, the
    index becomes the bank slot. Digits then skip the pre-rendered shared digit cells
    and take the per-occurrence path, so fixed-pitch text on the same screen keeps the
    stock numerals. The text code at 0x70000060 is untouched: metric selection and
    measurement still see the stored character.

    at, v0, v1 and a0 are dead at the hook; t8/t9 are saved. ``site`` is the address
    of the two displaced instructions (lui at,0x7000; lhu v0,0x62(at)).
    """
    a=Asm()
    a.i(15,'zero','at',0x7000);a.i(0x25,'at','v0',0x62)
    a.i(0x25,'at','a0',0x60)
    a.i(13,'zero','v1',0x824f);a.r('a0','v1','v1',0x23)
    a.i(0xb,'v1','at',10);a.branch(5,'at','zero','scene')
    for first in (0x8260-0x824f,0x8281-0x824f):
        a.i(9,'v1','at',-first);a.i(0xb,'at','at',26);a.branch(5,'at','zero','scene')
    for index,code in enumerate(punctuation):
        a.i(9,'zero','v1',76+index);a.i(13,'zero','at',code);a.branch(4,'a0','at','scene')
    a.branch(4,'zero','zero','resume')
    a.label('scene')
    a.i(9,'sp','sp',-32);a.i(0x1f,'sp','t8',0);a.i(0x1f,'sp','t9',16)
    # Only strings captured by the draw entry: the code just read is at s4-2.
    a.li('at',globals_);a.i(0x23,'at','t8',0);a.branch(4,'t8','zero','out')
    a.i(9,'s4','t9',-2);a.r('t9','t8','t9',0x2b);a.branch(5,'t9','zero','out')
    a.i(0x23,'at','t8',4);a.r('t8','s4','t9',0x2b);a.branch(5,'t9','zero','out')
    # Cell size exactly as the draw selector reads it: explicit record size, else state.
    a.i(15,'zero','at',0x7000);a.i(0x21,'at','t8',0x68);a.branch(5,'t8','zero','state_size')
    a.i(0x21,'at','t8',0x3c);a.i(0x21,'at','t9',0x3e);a.branch(4,'zero','zero','lookup')
    a.label('state_size');a.li('at',state);a.i(0x21,'at','t8',0x38);a.i(0x21,'at','t9',0x3a)
    a.label('lookup');a.li('a0',descriptors)
    a.label('route');a.i(0x23,'a0','at',0);a.branch(4,'at','zero','out')
    a.branch(5,'at','t8','next');a.i(0x23,'a0','at',4);a.branch(4,'at','t9','hit')
    a.label('next');a.i(9,'a0','a0',24);a.branch(4,'zero','zero','route')
    a.label('hit')
    a.i(0x1e,'sp','t8',0);a.i(0x1e,'sp','t9',16);a.i(9,'sp','sp',32)
    a.i(9,'v1','v0',bank_base);a.i(15,'zero','at',0x7000);a.i(0x29,'at','v0',0x62)
    a.i(0xb,'v1','a0',10);a.branch(4,'a0','zero','resume')
    a.i(0x2b,'at','v0',0);a.i(0x25,'at','a0',0x60);a.jump(dynamic_path)
    a.label('out')
    a.i(0x1e,'sp','t8',0);a.i(0x1e,'sp','t9',16);a.i(9,'sp','sp',32)
    a.label('resume');a.jump(site+8)
    return a.finish()
