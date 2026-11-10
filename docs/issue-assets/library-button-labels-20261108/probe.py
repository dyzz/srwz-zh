import sys
from pathlib import Path
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'tools'))
from srwz.armsx2_runtime import Armsx2Session
from srwz.armsx2_text_probe import trace_commands
out=R/'work/runtime/armsx2/library-button-labels-20261108'
with Armsx2Session(R/'build/iso/special-disc/sp-current.iso',R/'work/runtime/armsx2/library-size-width-iso-20261106/save/Mcd001.ps2',out,renderer='metal',upscale=4) as vm:
 vm.run(1800);vm.cmd(f"load {R/'work/runtime/armsx2/library-size-width-iso-20261106/lily-top.p2s'}");vm.run(60)
 vm.cmd('trace 13b5f0 name=glyph @70000060:2 s0:32')
 vm.cmd('trace 22a200 name=label a0:12 a1:16 @47b610:32 stack')
 vm.run(1);vm.cmd(f'tracedump {out}/text.jsonl');vm.cmd('untrace');vm.shot('baseline');(out/'ram.bin').write_bytes(vm.read_ram(0,33554432))
 vm.cmd('poke 2168e8 9c26080c');vm.run(2);vm.shot('regular-labels')
