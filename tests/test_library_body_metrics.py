"""The edition-specific native hook must fix inherited geometry without changing controls."""
import json
from pathlib import Path
import struct
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from srwz.library_body_metrics import EDITIONS,CAVE_SIZE,apply_library_body_metrics,trampoline,write_ranges
from srwz.library_typography import library_typography
from build_library_v02_component import reflow_body
from srwz.text import CONTROL_NOTATION
ROOT=Path(__file__).resolve().parents[1]

class LibraryBodyPatchTests(unittest.TestCase):
    def fixture(self,ed):
        s=EDITIONS[ed];b=bytearray(s['cave']-s['delta']+CAVE_SIZE)
        h=s['hook']-s['delta'];b[h-8:h]=bytes.fromhex('2d4080022110c200')
        struct.pack_into('<I',b,h,3<<26 | s['draw']>>2);b[h+4:h+8]=bytes.fromhex('000040a0')
        return bytes(b)

    def test_only_owned_bytes_change_and_reapplication_is_exact(self):
        for ed in EDITIONS:
            with self.subTest(edition=ed):
                native=self.fixture(ed);out,report=apply_library_body_metrics(native,ed)
                changed={i for i,(a,b) in enumerate(zip(native,out)) if a!=b}
                allowed={i for lo,hi in write_ranges(ed) for i in range(lo,hi)}
                self.assertTrue(changed);self.assertLessEqual(changed,allowed)
                self.assertEqual(len(out),len(native));self.assertEqual(apply_library_body_metrics(out,ed)[0],out)
                for bad_at in (write_ranges(ed)[0][0],write_ranges(ed)[1][0]):
                    bad=bytearray(native);bad[bad_at]^=1
                    with self.assertRaises(ValueError):apply_library_body_metrics(bytes(bad),ed)

    def test_legacy_controls_compile_to_native_restore_without_visible_change(self):
        old='<width:16><space:16>中文<width:0E><space:0C>Geo<width:16><space:16>圣剑99%中文'
        compiled=library_typography(old,'DSC2');flow,widths=reflow_body(compiled,16)
        self.assertNotIn('<width:16>',flow);self.assertNotIn('<space:16>',flow)
        self.assertIn('<height:0C>Geo',flow)
        self.assertIn('<height:0C>圣剑',flow)
        self.assertNotIn('<height:0A>',flow)
        self.assertEqual(CONTROL_NOTATION.sub('',flow).replace('\n',''),CONTROL_NOTATION.sub('',old))
        self.assertTrue(all(x<=16 for x in widths))
        self.assertEqual(library_typography(compiled,'DSC2'),compiled)

class NativeLibraryBodyPatchTests(unittest.TestCase):
    def test_all_three_native_executables_and_inherited_height(self):
        try:
            from unicorn import Uc,UC_ARCH_MIPS,UC_MODE_MIPS64,UC_MODE_LITTLE_ENDIAN,UC_HOOK_CODE
            from unicorn.mips_const import UC_MIPS_REG_8,UC_MIPS_REG_16,UC_MIPS_REG_17,UC_MIPS_REG_20,UC_MIPS_REG_29,UC_MIPS_REG_RA,UC_MIPS_REG_PC
        except ImportError:self.skipTest('optional Unicorn MIPS64 is unavailable')
        from srwz.iso9660 import member_map,scan_iso9660
        for ed,s in EDITIONS.items():
            cfg=json.loads((ROOT/f'config/editions/{ed}/edition.json').read_text());iso=ROOT/cfg['source_iso']['path']
            if not iso.is_file():self.skipTest('native source disc unavailable')
            member=member_map(scan_iso9660(iso))[cfg['executable']['member']]
            with iso.open('rb') as f:f.seek(member.extent_lba*2048);native=f.read(member.size)
            import hashlib
            self.assertEqual(hashlib.sha256(native).hexdigest(),cfg['executable']['sha256'])
            patched,_=apply_library_body_metrics(native,ed)
            original=(ROOT/'work/disc/SLPS_258.87').read_bytes()
            width_pattern=original[0x13A470-0xFE580:0x13A48C-0xFE580]
            width_off=native.find(width_pattern)
            self.assertGreaterEqual(width_off,0)
            self.assertEqual(native.find(width_pattern,width_off+1),-1)
            # Exercise the real trampoline; stop at the unchanged original callee.
            for height,advance_y in ((12,14),(10,12)):
                for inherited in (7,10,11,15):
                    with self.subTest(edition=ed,height=height,inherited=inherited):
                        u=Uc(UC_ARCH_MIPS,UC_MODE_MIPS64|UC_MODE_LITTLE_ENDIAN);u.mem_map(0,32<<20)
                        ph=struct.unpack_from('<I',native,28)[0]
                        _,load_off,load_va,_,file_size,*_=struct.unpack_from('<8I',native,ph)
                        u.mem_write(load_va,native[load_off:load_off+file_size])
                        u.mem_map(0x70000000,0x1000)
                        u.mem_write(s['cave'],trampoline(ed));desc=0x1800000
                        u.mem_write(desc+14,bytes([21,height,21,advance_y]*2))
                        u.mem_write(s['state'],struct.pack('<4H',22,inherited,22,11))
                        u.reg_write(UC_MIPS_REG_8,desc);u.reg_write(UC_MIPS_REG_RA,s['hook']+8)
                        def stop(uc,pc,size,data):
                            if pc==s['draw']:uc.emu_stop()
                        hook=u.hook_add(UC_HOOK_CODE,stop);u.emu_start(s['cave'],0,count=100)
                        u.hook_del(hook)
                        self.assertEqual(u.reg_read(UC_MIPS_REG_PC),s['draw'])
                        self.assertEqual(u.reg_read(UC_MIPS_REG_RA),s['hook']+8)
                        self.assertEqual(u.reg_read(UC_MIPS_REG_8),desc)
                        self.assertEqual(struct.unpack('<4H',bytes(u.mem_read(s['state'],8))),(21,height,21,advance_y))
                        # Run the unchanged native classifier initializer after the hook.
                        stack=0x1FF0000;u.reg_write(UC_MIPS_REG_29,stack)
                        u.reg_write(UC_MIPS_REG_16,desc)
                        for off in (0,8,16,24,32):u.mem_write(stack+off,b'\x01')
                        end=s['draw']+0x6C
                        def stop_at(uc,pc,size,data):
                            if pc==end:uc.emu_stop()
                        hook=u.hook_add(UC_HOOK_CODE,stop_at)
                        u.emu_start(s['draw']+0x48,0,count=200);u.hook_del(hook)
                        self.assertEqual(u.reg_read(UC_MIPS_REG_PC),end)
                        # The classified geometry and explicit geometry now agree.
                        self.assertEqual(struct.unpack('<2H',bytes(u.mem_read(s['state']+0x24,4))),(21,height))
                        # Execute actual width/space parser instructions, then restore Chinese.
                        for handler,param,expected_width,expected_space in (
                                (width_off+s['delta'],14,14,21),
                                (width_off+s['delta']+0x40,12,14,12),
                                (width_off+s['delta'],21,21,12),
                                (width_off+s['delta']+0x40,21,21,21)):
                            text=0x1900000;u.mem_write(text,bytes([param]))
                            u.reg_write(UC_MIPS_REG_20,text)
                            u.reg_write(UC_MIPS_REG_17,s['state']-0x14)
                            end=width_off+s['delta']-0xE0
                            hook=u.hook_add(UC_HOOK_CODE,stop_at)
                            u.emu_start(handler,0,count=30);u.hook_del(hook)
                            self.assertEqual(u.reg_read(UC_MIPS_REG_PC),end)
                            self.assertEqual(struct.unpack('<4H',bytes(u.mem_read(s['state'],8))),
                                             (expected_width,height,expected_space,advance_y))
                        # Temporary optical-height compensation must restore the
                        # next Chinese glyph and preserve the row's vertical advance.
                        for value in (height + 2, height + 1, height):
                            u.mem_write(text,bytes([value]))
                            u.reg_write(UC_MIPS_REG_20,text)
                            hook=u.hook_add(UC_HOOK_CODE,stop_at)
                            u.emu_start(width_off+s['delta']+0x20,0,count=30)
                            u.hook_del(hook)
                            self.assertEqual(struct.unpack('<4H',bytes(u.mem_read(s['state'],8))),
                                             (21,value,21,advance_y))

            # Parser/control code outside the tiny hook/cave remains byte exact.
            allowed={i for lo,hi in write_ranges(ed) for i in range(lo,hi)}
            self.assertTrue(all(a==b or i in allowed for i,(a,b) in enumerate(zip(native,patched))))
