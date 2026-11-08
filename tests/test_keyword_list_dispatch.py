"""Run the emitted descriptor-based measurement dispatcher, including UI rejection."""
import struct,unittest
from test_library_protagonist_names import run_mips
from tools.srwz.proportional_scene_dispatch import style_selector
from tools.srwz.proportional_hooks import Asm

class KeywordListDispatchTests(unittest.TestCase):
 def test_list_width_selects_metrics_and_unknown_width_stays_native(self):
  code,table,state,globals_,native,generic,stop=0x1000,0x2000,0x3000,0x4000,0x5000,0x5100,0x5200
  blob=style_selector([],[],globals_,0,native,generic,'measure',state=state,descriptors=table)
  for automatic in [0,1]:
   for width,height,selected in [(18,12,True),(18,10,True),(18,9,True),(17,12,False),(21,12,True)]:
    with self.subTest(automatic=automatic,width=width,height=height):
     ram=bytearray(0x10000);ram[code:code+len(blob)]=blob
     struct.pack_into('<12I',ram,table,18,12,0x6000,0x6100,14,0x6200,21,12,0x6300,0x6400,14,0x6500)
     struct.pack_into('<hh',ram,state+(0x38 if automatic else 0x14),width,height)
     struct.pack_into('<h',ram,state+0x48,automatic)
     for addr,value in [(native,0),(generic,1)]:
      a=Asm();a.i(9,'zero','v0',value);a.jump(stop);b=a.finish();ram[addr:addr+len(b)]=b
     regs=[i*17 for i in range(32)];regs[0]=0;regs[29]=0xf000;before=regs.copy()
     run_mips(ram,regs,code,stop)
     self.assertEqual(regs[2],int(selected));before[2]=int(selected);self.assertEqual(regs,before)
     if selected:self.assertEqual(struct.unpack_from('<II',ram,globals_+8),(0x6000,0x6100) if width==18 else (0x6300,0x6400))
     else:self.assertEqual(ram[globals_:globals_+24],bytes(24))
