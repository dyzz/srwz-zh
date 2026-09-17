"""Execute assembled hook instructions in Unicorn MIPS64; not PS2 graphics proof."""
import json
import struct
import unittest
from pathlib import Path
try:
    from unicorn import Uc, UC_ARCH_MIPS, UC_MODE_MIPS64, UC_MODE_LITTLE_ENDIAN, UC_HOOK_CODE
    from unicorn.mips_const import *
except ImportError:
    raise unittest.SkipTest("optional Unicorn MIPS64 runtime not installed")
BASE=0x3f6000; DATA=BASE+0x600; WORLD=0x5f9d50; SCENE=WORLD+0x3a80
STOP=0x3e0000; CTX=0x6cee00
class Machine:
    def __init__(self):
        self.u=Uc(UC_ARCH_MIPS,UC_MODE_MIPS64|UC_MODE_LITTLE_ENDIAN)
        self.u.mem_map(0,32<<20)
        self.u.mem_write(BASE,HOOK)
        self.u.mem_write(WORLD_STEP,struct.pack('<II',0x03e00008,0))
        self.u.reg_write(UC_MIPS_REG_SP,0x1ff0000)
        self.calls=0; self.result=0
        def code(uc, address, size, _):
            if address==WORLD_STEP:
                self.calls+=1; uc.reg_write(UC_MIPS_REG_V0,self.result)
        self.u.hook_add(UC_HOOK_CODE,code)
        self.w(ACTION_INDEX,1);self.w(ACTION_COUNT,4);self.w(ACTION_SCENE_COUNT+0x1d4,1)
        self.b(WORLD+0x400,1);self.h(WORLD+0xe0,0x11)
        self.b(PAD_TRIG,0x80)
        self.w(DATA+0x40,5);self.w(DATA+0x44,7);self.w(DATA+0x48,11)
        self.scene(SCENE)
        for g in range(2):
            for s in range(4):self.b(WORLD+0x450+g*0x14c0+s*0x510,4)
    def w(self,a,v):self.u.mem_write(a,struct.pack('<I',v))
    def h(self,a,v):self.u.mem_write(a,struct.pack('<H',v))
    def b(self,a,v):self.u.mem_write(a,bytes([v]))
    def rw(self,a):return struct.unpack('<I',self.u.mem_read(a,4))[0]
    def rb(self,a):return self.u.mem_read(a,1)[0]
    def scene(self,a):
        self.w(a+4,1);self.w(a+0x394,0x6ccb20)
        self.b(a+0x338,5);self.b(a+0x33a,1)
        for i,t in enumerate([0x10,0x11,0x21,0x1e,0x1f]):self.h(a+0x18+i*8,t)
    def frame(self):
        self.u.reg_write(UC_MIPS_REG_RA,STOP)
        self.u.emu_start(BASE,STOP,count=5000)
        assert self.u.reg_read(UC_MIPS_REG_PC)==STOP
ROOT = Path(__file__).resolve().parents[1]

class OriginalNativeTailTests(unittest.TestCase):
    edition = "original"

    def setUp(self):
        global HOOK, WORLD, SCENE, CTX, WORLD_STEP, ACTION_INDEX, ACTION_COUNT
        global ACTION_SCENE_COUNT, PAD_TRIG, READ_BUSY, APPEND_RESUME, APPEND_ENTRY
        contract = json.loads((ROOT / "config/full-story-components.json").read_text())["battle_square_skip"]["editions"][self.edition]
        syms = {k: int(v, 0) for k, v in contract["symbols"].items()}
        HOOK = bytes.fromhex(contract["hook_hex"])
        WORLD, CTX = syms["WORLD"], syms["CTX"]
        SCENE = WORLD + 0x3a80
        WORLD_STEP, APPEND_RESUME = syms["FN_WORLD_STEP"], syms["FN_APPEND_RESUME"]
        APPEND_ENTRY = APPEND_RESUME - 8
        ACTION_INDEX, ACTION_COUNT = syms["ACTION_INDEX"], syms["ACTION_COUNT"]
        ACTION_SCENE_COUNT = syms["ACTION_SCENE_COUNT"]
        PAD_TRIG, READ_BUSY = syms["PAD_TRIG"], syms["READ_BUSY"]

    def test_cleanup_then_terminal_and_busy_preserved(self):
        m=Machine();m.b(SCENE+0x770,9);m.b(SCENE+0xd90,8)
        before=bytes(m.u.mem_read(SCENE+0x18,0x320))
        m.frame();self.assertEqual(m.rb(SCENE+0x33a),2)
        m.frame();self.assertEqual(m.rb(SCENE+0x33a),2)
        self.assertEqual(m.rw(DATA+0xc),1)
        m.b(SCENE+0x33a,3);m.frame()
        self.assertEqual(m.rb(SCENE+0x33a),4);self.assertEqual(m.rw(DATA+0x2c),1)
        self.assertEqual(m.rb(SCENE+0x770),9);self.assertEqual(m.rb(SCENE+0xd90),8)
        self.assertEqual(bytes(m.u.mem_read(SCENE+0x18,0x320)),before)
        m.frame();self.assertEqual(m.rw(DATA+0x2c),1);self.assertEqual(m.calls,4)
    def test_loading_gates(self):
        for addr in [CTX+1,READ_BUSY]:
            with self.subTest(addr=addr):
                m=Machine();m.b(addr,1);m.frame()
                self.assertEqual(m.rb(SCENE+0x33a),1);self.assertEqual(m.rb(CTX+2),0)
                self.assertEqual(m.rw(DATA+0x24),1);self.assertEqual(m.rw(DATA),1)
                m.b(addr,0);m.frame();self.assertEqual(m.rb(SCENE+0x33a),2)
    def test_all_sprite_slots_gate_loading_and_cleanup(self):
        for g in range(2):
            for s in range(4):
                for state in [2,3,6]:
                    with self.subTest(g=g,s=s,state=state):
                        m=Machine();m.b(WORLD+0x450+g*0x14c0+s*0x510,state);m.frame()
                        self.assertEqual(m.rb(SCENE+0x33a),1)
    def test_stale_ticket_does_not_modify_new_queue(self):
        for address,value in [(DATA+0x40,6),(DATA+0x48,12),(SCENE+0x394,0x6ccbe0)]:
            with self.subTest(address=address):
                m=Machine();m.frame();m.b(SCENE+0x33a,3);m.w(address,value);m.frame()
                self.assertEqual(m.rb(SCENE+0x33a),3);self.assertEqual(m.rw(DATA+0x28),1)
    def test_unknown_or_invalid_queues(self):
        for count,pc,tag,obj in [(2,1,0x21,1),(101,1,0x21,1),(5,5,0x21,1),(5,1,0x22,1),(5,1,0x21,0)]:
            with self.subTest(count=count,pc=pc,tag=tag,obj=obj):
                m=Machine();m.b(SCENE+0x338,count);m.b(SCENE+0x33a,pc)
                m.h(SCENE+0x28,tag);m.w(SCENE+0x394,obj);m.frame()
                self.assertEqual(m.rb(SCENE+0x33a),pc);self.assertEqual(m.rw(DATA+0xc),0)
    def test_passive_no_press(self):
        m=Machine();m.b(PAD_TRIG,0);m.frame()
        self.assertEqual(m.rw(DATA),0);self.assertEqual(m.rb(SCENE+0x33a),1);self.assertEqual(m.calls,1)
    def test_intro_native_fast_only(self):
        m=Machine();m.w(ACTION_INDEX,0);m.frame()
        self.assertEqual(m.rb(CTX+2),1);self.assertEqual(m.rb(SCENE+0x33a),1);self.assertEqual(m.calls,1)
    def test_action_change_or_whole_skip_cancels(self):
        for addr,value in [(ACTION_INDEX,2),(CTX,1),(CTX+3,1)]:
            m=Machine();m.frame();m.w(addr,value);m.b(SCENE+0x33a,3);m.frame()
            self.assertEqual(m.rw(DATA),0);self.assertEqual(m.rb(SCENE+0x33a),3)
    def test_selected_scene_only(self):
        for tag in [0x2c,0x2e]:
            m=Machine();m.scene(SCENE+0x1160);m.w(ACTION_SCENE_COUNT+0x1d4,2)
            m.h(WORLD+0xe0,tag);m.w(WORLD+0xe4,0x700000);m.b(0x700000,1);m.frame()
            self.assertEqual(m.rb(SCENE+0x33a),1);self.assertEqual(m.rb(SCENE+0x1160+0x33a),2)
    def test_all_scene_wait(self):
        m=Machine();m.scene(SCENE+0x1160);m.w(ACTION_SCENE_COUNT+0x1d4,2);m.frame()
        self.assertEqual(m.rb(SCENE+0x33a),2);self.assertEqual(m.rb(SCENE+0x1160+0x33a),2)
    def test_queue_generations_and_append_replay(self):
        for queue,offset in [(SCENE+0x18,0x40),(SCENE+0x1178,0x44),(WORLD+0xe0,0x48),(0x710000,None)]:
            for index in [0,1]:
                m=Machine();m.b(queue+0x320,index)
                before=[m.rw(DATA+o) for o in [0x40,0x44,0x48]]
                m.u.reg_write(UC_MIPS_REG_A0,queue);m.u.reg_write(UC_MIPS_REG_A1,0x21)
                m.u.emu_start(BASE+0x500,APPEND_RESUME,count=100)
                self.assertEqual(m.u.reg_read(UC_MIPS_REG_V0),index*8)
                self.assertEqual(m.u.reg_read(UC_MIPS_REG_A0),queue)
                self.assertEqual(m.u.reg_read(UC_MIPS_REG_A1),0x21)
                for j,o in enumerate([0x40,0x44,0x48]):self.assertEqual(m.rw(DATA+o),before[j]+(index==0 and offset==o))
    def test_register_preservation(self):
        m=Machine();regs=[UC_MIPS_REG_S0,UC_MIPS_REG_S1,UC_MIPS_REG_S2]
        values=[0x1234567800000000+i for i in range(3)]
        for reg,value in zip(regs,values):m.u.reg_write(reg,value)
        m.frame()
        for reg,value in zip(regs,values):self.assertEqual(m.u.reg_read(reg),value)
        self.assertEqual(m.u.reg_read(UC_MIPS_REG_SP),0x1ff0000)
    def test_end_clears_request(self):
        m=Machine();m.result=1;m.frame();self.assertEqual(m.rw(DATA),0);self.assertEqual(m.rw(DATA+0x10),1)
    def test_native_cleanup_already_done(self):
        m=Machine();m.b(SCENE+0x33a,3);m.frame()
        self.assertEqual(m.rb(SCENE+0x33a),4);self.assertEqual(m.rw(DATA+0xc),0)
    def test_non_wait_world_command(self):
        for tag in [3,0xb,0x19]:
            m=Machine();m.h(WORLD+0xe0,tag);m.frame();self.assertEqual(m.rb(SCENE+0x33a),1)
    def test_complete_append_matches_original_over_multiple_commands(self):
        path = ROOT / ("work/disc/SLPS_258.87" if self.edition == "original" else "work/analysis/v040-best-chart-20260909/best/SLPS_732.70")
        if not path.exists():
            self.skipTest("native executable not extracted")
        offset = APPEND_ENTRY - 0x100000 + 0x1a80
        raw = path.read_bytes()[offset:offset+0x64]
        original=Machine();hooked=Machine()
        for machine in [original,hooked]:
            machine.u.mem_write(APPEND_ENTRY,raw)
            machine.b(WORLD+0x400,0);machine.b(WORLD+0x401,0)
        for i,tag in enumerate([0x17,5,6,3,0x22,0x23,0x27,0xd,0xe,0xf,0x14,0x18,0x19,0xa]):
            for machine,entry in [(original,APPEND_ENTRY),(hooked,BASE+0x500)]:
                machine.u.reg_write(UC_MIPS_REG_A0,WORLD+0xe0)
                machine.u.reg_write(UC_MIPS_REG_A1,tag)
                machine.u.reg_write(UC_MIPS_REG_A2,16 if i==3 else 0)
                machine.u.reg_write(UC_MIPS_REG_T0,0x123400000000+0x50+i)
                machine.u.reg_write(UC_MIPS_REG_T1,0x123400000000+0x60+i)
                machine.u.reg_write(UC_MIPS_REG_RA,STOP)
                machine.u.emu_start(entry,STOP,count=200)
                self.assertEqual(machine.u.reg_read(UC_MIPS_REG_T0),0x123400000000+0x50+i)
                self.assertEqual(machine.u.reg_read(UC_MIPS_REG_T1),0x123400000000+0x60+i)
            self.assertEqual(bytes(original.u.mem_read(WORLD+0xe0,0x324)),bytes(hooked.u.mem_read(WORLD+0xe0,0x324)))
        self.assertEqual(hooked.rb(WORLD+0x400),14)
        self.assertEqual(hooked.rw(DATA+0x48),12)
    def test_ee_ram_aliases_preserve_pointer_and_track_generation(self):
        for alias in [0x20000000,0x30000000]:
            for queue,offset in [(SCENE+0x18,0x40),(SCENE+0x1178,0x44),(WORLD+0xe0,0x48)]:
                m=Machine();ptr=queue+alias
                m.u.mem_map(ptr&~0xfff,0x2000);m.b(ptr+0x320,0)
                old=m.rw(DATA+offset)
                m.u.reg_write(UC_MIPS_REG_A0,ptr)
                m.u.emu_start(BASE+0x500,APPEND_RESUME,count=200)
                self.assertEqual(m.rw(DATA+offset),old+1)
                self.assertEqual(m.u.reg_read(UC_MIPS_REG_A0),ptr)
                self.assertEqual(m.rw(DATA+0x50),ptr)
class BestNativeTailTests(OriginalNativeTailTests):
    edition = "best"

if __name__ == '__main__':
    unittest.main(verbosity=2)
