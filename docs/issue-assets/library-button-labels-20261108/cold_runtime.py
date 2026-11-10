import sys
from pathlib import Path
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'tools'))
from srwz.armsx2_runtime import Armsx2Session
with Armsx2Session(R/'build/iso/library-button-labels-20261108/sp.iso',R/'work/runtime/armsx2/library-size-width-iso-20261106/save/Mcd001.ps2',R/'work/runtime/armsx2/library-button-labels-20261108/cold',renderer='metal',upscale=4) as vm:
 vm.run(1800);vm.press('start');vm.run(180);vm.shot('title')
 vm.press('right');vm.run(30);vm.press('circle');vm.run(300);vm.shot('library-menu')
 vm.press('down');vm.run(30);vm.press('circle');vm.run(300);vm.shot('character-list')
 vm.press('circle');vm.run(180);vm.shot('character-detail')
