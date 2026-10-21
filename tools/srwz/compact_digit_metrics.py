"""Automatic height for compact fullwidth digits in the native text parser.

Only selected width14/advance12 digits at native heights9..12 are reduced
by one native height unit.
An explicit height control in the current parser call suppresses automatic
adjustment. The companion optical parser owns the initialized SP+59 marker.
Temporary geometry changes do not affect persistent metrics, pen or advance.
Native classification is compacted equivalently to provide existing code space.
"""
import struct

NATIVE_CLASSIFICATION = bytes.fromhex(
    '0070013cffff4430500020ac928401342a08810044002010000000004f002382'
    '0b0060109f8201342a08810008002010408103342a1883000500601400000000'
    '010003240070013c37000010500023ac4e0023820c006010928401342a088100'
    '09002010408303342a1883000600601400000000010003240070013c2a000010'
    '500023ac000000004b0023820c0060107a8201342a0881000900201060820334'
    '2a1883000600601400000000010003240070013c1c000010500023ac00000000'
    '4d0023820c006010f28201342a088100090020109f8203342a18830006006014'
    '00000000010003240070013c0e000010500023ac000000004c0023820a006010'
    '9b8201342a08810007002010818203342a188300040060140000000001000324'
    '0070013c500023ac0070013c5000238c09006010000000004000238e0070013c'
    '3c0023ac4400238e0070013c08000010380023ac000000003800238e0070013c'
    '3c0023ac3c00238e0070013c380023ac'
)

class Asm:
 def __init__(self,base):self.base=base;self.words=[];self.labels={};self.fix=[]
 def emit(self,*words):self.words.extend(words)
 def label(self,name):self.labels[name]=self.base+len(self.words)*4
 def branch(self,op,rs,rt,label):self.fix.append((len(self.words),label));self.emit(op<<26|rs<<21|rt<<16,0)
 def jump(self,target):self.emit(2<<26|(target>>2),0)
 def bytes(self):
  for i,label in self.fix:self.words[i]|=((self.labels[label]-(self.base+i*4+4))//4)&65535
  return struct.pack('<'+'I'*len(self.words),*self.words)
def regions(delta):
 start=0x13a630+delta;end=0x13a7a0+delta;a=Asm(start)
 # Scratch selector flag must retain native 0/1 semantics.
 a.emit(0x3c017000,0xac200050)
 for k,(flag,lo,hi) in enumerate([(0x4f,0x8140,0x829f),(0x4e,0x8340,0x8492),(0x4b,0x8260,0x827a),(0x4d,0x829f,0x82f2),(0x4c,0x8281,0x829b)]):
  a.emit(0x34040000|lo,0x00442023,0x2c840000|(hi-lo));a.branch(4,4,0,f'next{k}')
  a.emit(0x82240000|flag);a.branch(5,4,0,'use_b');a.label(f'next{k}')
 a.emit(0x26240038);a.jump(start+0xE8) # fixed shared copy block
 a.label('use_b');a.emit(0x24030001,0xac230050,0x26240040);a.jump(start+0xE8)
 assert len(a.words)*4<=0xE8
 a.emit(*([0]*((0xE8-len(a.words)*4)//4)))
 a.emit(0x8c830000,0xac23003c,0x8c830004,0xac230038);a.jump(end)
 a.label('auto_digit')
 a.emit(0x93a30059);a.branch(5,3,0,'resume')
 a.emit(0x3c017000,0x94230060,0x3404824f,0x00641823,0x2c63000a);a.branch(4,3,0,'resume')
 a.emit(0x9423003c,0x2463fff2);a.branch(5,3,0,'resume')
 a.emit(0x94230038,0x2463fff4);a.branch(5,3,0,'resume')
 a.emit(0x8423003e,0x2464fff7,0x2c840004);a.branch(4,4,0,'resume')
 a.emit(0x2463ffff,0xa423003e)
 a.label('resume');a.jump(end+8)
 code=a.bytes();assert len(code)<=end-start,(len(code),end-start)
 code=code.ljust(end-start,b'\0')
 hook=struct.pack('<I',2<<26|a.labels['auto_digit']>>2)
 return [(start,NATIVE_CLASSIFICATION,code),(end,struct.pack('<I',0x3c017000),hook)]
