"""Reserve tag-free runtime payload below existing heaps without growing ELFs.

Only audited current layouts are accepted. This reserves storage; it does not
install renderer hooks or claim cold-boot/runtime validation.
"""
import struct
from hashlib import sha256

LAYOUTS={
 'original':dict(base=0x789e00,offset=0x34d700,capacity=0x2900,slot=208,
                 marker=(1,0x34d700,0x789d00,0x789d00,0,0,6,16),heap=0x7a0000,heap_pointer=0x3f3fb4),
 'best':dict(base=0x78a600,offset=0x34df00,capacity=0x2900,slot=208,
             marker=(1,0x34df00,0x78a500,0x78a500,0,0,6,16),heap=0x7a0000,heap_pointer=0x3f4734),
 'sp':dict(base=0x81e200,offset=0x3cb700,capacity=0x1900,slot=72,
           marker=None,heap=0x8c0000,heap_pointer=0x44e734),
}

def reserve_payload(elf,payload,edition):
 if edition not in LAYOUTS:raise ValueError('Unaudited edition')
 c=LAYOUTS[edition];b=bytearray(elf)
 if b[:7]!=b'\x7fELF\x01\x01\x01':raise ValueError('Expected little-endian ELF32')
 ph=struct.unpack_from('<I',b,28)[0];ent,n=struct.unpack_from('<HH',b,42)
 if ent!=32 or ph+n*ent>len(b):raise ValueError('Invalid program headers')
 hs=[struct.unpack_from('<8I',b,ph+i*32) for i in range(n)]
 def off(addr):
  for t,o,v,p,sz,mem,fl,al in hs:
   if t==1 and v<=addr and addr+4<=v+sz:return o+addr-v
  raise ValueError('Heap pointer outside file-backed segment')
 if struct.unpack_from('<I',b,off(c['heap_pointer']))[0]!=c['heap']:raise ValueError('Heap boundary drift')
 if not payload or len(payload)>c['capacity']:raise ValueError('Payload capacity exceeded or empty')
 start=c['base'];end=start+c['capacity'];fo=c['offset'];fz=fo+c['capacity']
 if end>c['heap'] or fz>len(b):raise ValueError('Reservation outside safe bounds')
 for i,(t,o,v,p,sz,mem,fl,al) in enumerate(hs):
  if t==1 and mem and max(start,v)<min(end,v+mem):raise ValueError('Payload overlaps loaded memory')
  if sz and max(fo,o)<min(fz,o+sz):raise ValueError('Payload overlaps existing file-backed segment')
 # This gap contains only the linker section directory, names and comments.
 # Remove that nonloaded metadata explicitly, never mistake it for free zeros.
 sh=struct.unpack_from('<I',b,32)[0];se,sn,si=struct.unpack_from('<HHH',b,46)
 if se!=40 or not sn or not fo<=sh<sh+se*sn<=fz:raise ValueError('Unexpected section directory')
 covered=bytearray(c['capacity'])
 covered[sh-fo:sh+se*sn-fo]=b'\x01'*(se*sn)
 for i in range(sn):
  _,typ,flags,addr,off_,size,*_=struct.unpack_from('<10I',b,sh+i*se)
  if typ==8 or not size:continue
  if max(fo,off_)>=min(fz,off_+size):continue
  if flags&2 or not fo<=off_<off_+size<=fz:raise ValueError('Loaded section overlaps payload metadata gap')
  covered[off_-fo:off_+size-fo]=b'\x01'*size
 if any(v and not covered[i] for i,v in enumerate(b[fo:fz])):raise ValueError('Unknown nonzero data in metadata gap')
 b[fo:fz]=bytes(c['capacity'])
 struct.pack_into('<I',b,32,0);struct.pack_into('<HHH',b,46,0,0,0)
 slot=c['slot'];header=ph+slot*32
 if c['marker'] is not None:
  if slot>=n or hs[slot]!=c['marker']:raise ValueError('End marker drift')
 else:
  if slot!=n:raise ValueError('Program header count drift')
  first=min(h[1] for h in hs if h[4])
  if header+32>first or any(b[header:header+32]):raise ValueError('No free program header')
  struct.pack_into('<H',b,44,n+1)
 b[fo:fo+len(payload)]=payload
 struct.pack_into('<8I',b,header,1,fo,start,start,len(payload),c['capacity'],7,16)
 assert len(b)==len(elf)
 return bytes(b),dict(edition=edition,base=start,fileOffset=fo,capacity=c['capacity'],
  payloadBytes=len(payload),headerSlot=slot,heapUnchanged=True,elfSizeUnchanged=True,
  sourceSha256=sha256(elf).hexdigest(),resultSha256=sha256(b).hexdigest(),
  nonloadedSectionMetadataRemoved=True,runtimeVerified=False)


def build_story_payload(registry, *, owner, end, draw_owner, draw_end, chinese_punctuation=False, dynamic_draw=False):
 """Pack the verified Original story route with explicit ownership bounds.

 Bounds are caller-supplied evidence, not inferred universal story ownership.
 Current callers use a controlled replay; other scenes need their own routes.
 """
 from .proportional_hooks import draw_hook,measure_hook,keyword_underline_hooks,cjk_runtime_table
 from .proportional_metrics import runtime_table
 c=LAYOUTS['original'];base=c['base'];table=base+0x800
 for lo,hi in [(owner,end),(draw_owner,draw_end)]:
  if not 0<=lo<hi<=0x2000000:raise ValueError('Invalid EE source range')
 copy,restore,dispatch=keyword_underline_hooks(base+0x1800,base)
 cjk_table=base+0xa00 if chinese_punctuation else None
 draw_bounds=(('s5',0),('s6',1)) if dynamic_draw else (draw_owner,draw_end)
 blocks=[('draw',0,draw_hook(*draw_bounds,table,14,caller=0x2253cc,cjk_table=cjk_table,native_size=(21,12) if dynamic_draw else None)),
         ('measure',0x400,measure_hook(owner,end,table,cjk_table=cjk_table)),
         ('metrics',0x800,runtime_table(registry['profiles']['story'])),
         ('underline_copy',0xc00,copy),('underline_restore',0xe00,restore),
         ('draw_dispatch',0x1000,dispatch),('scratch',0x1800,bytes(16))]
 if chinese_punctuation:blocks.append(('cjk_metrics',0xa00,cjk_runtime_table(registry['profiles']['story'])))
 payload=bytearray(0x1810);occupied=set();sections=[]
 for name,offset,data in blocks:
  positions=set(range(offset,offset+len(data)))
  if occupied&positions or offset+len(data)>len(payload):raise ValueError('Payload section collision')
  occupied|=positions;payload[offset:offset+len(data)]=data
  sections.append(dict(name=name,address=base+offset,size=len(data)))
 def words(*values):return struct.pack('<'+'I'*len(values),*values)
 patches=[
  (0x13ab58,words(0x8e230024,0xae030014),words(0x08000000|((base+0x1000)>>2),0)),
  (0x139b78,bytes.fromhex('00008b9062006011'),words(0x08000000|((base+0x400)>>2),0)),
  (0x2215f4,words(0x0c068464),words(0x0c000000|((base+0xc00)>>2))),
  (0x221628,words(0x26020002,0x02429021),words(0x0c000000|((base+0xe00)>>2),0)),
  (0x22163c,words(0x00022042,0x00641818,0x0283a021),words(0x3c010047,0x8423e340,0x0060a02d))]
 return bytes(payload),patches,dict(base=base,sections=sections,chinesePunctuation=chinese_punctuation,dynamicDraw=dynamic_draw,fontSha256=registry['fontSha256'],
  ownership=dict(measure=[owner,end],draw=list(draw_bounds),drawCaller=0x2253cc,
                 nativeDrawSize=[21,12] if dynamic_draw else None),
  scope='Original controlled story route; not universal surface coverage')


def install_story_payload(elf,registry,**ownership):
 payload,patches,report=build_story_payload(registry,**ownership)
 candidate,reservation=reserve_payload(elf,payload,'original');b=bytearray(candidate)
 ph=struct.unpack_from('<I',elf,28)[0];n=struct.unpack_from('<H',elf,44)[0]
 hs=[struct.unpack_from('<8I',elf,ph+i*32) for i in range(n)]
 report['patches']=[]
 for address,expected,replacement in patches:
  mappings=[o+address-v for t,o,v,p,sz,mem,fl,al in hs if t==1 and v<=address and address+len(expected)<=v+sz]
  if len(mappings)!=1:raise ValueError('Ambiguous hook mapping')
  offset=mappings[0]
  if elf[offset:offset+len(expected)]!=expected:raise ValueError(f'Hook preimage drift at {address:#x}')
  b[offset:offset+len(replacement)]=replacement
  report['patches'].append(dict(address=address,before=expected.hex(),after=replacement.hex()))
 report['reservation']=reservation;report['resultSha256']=sha256(b).hexdigest()
 return bytes(b),report
