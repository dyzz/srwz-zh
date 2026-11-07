import sys
from pathlib import Path
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'tools'))
from srwz.armsx2_runtime import Armsx2Session
ed=sys.argv[1] if len(sys.argv)>1 else 'original'
with Armsx2Session(R/f'build/iso/native-others-command-20261107/{ed}.iso',R/'work/verification/spirit-cost-production-20261010/best-cold/save/current-best.ps2',R/f'work/runtime/armsx2/native-others-command-20261107/{ed}',renderer='metal',upscale=4) as vm:
 def p(b,n=60):vm.press(b);vm.run(n)
 vm.run(1800);p('start',180);p('down');p('down');p('circle',500)
 p('r1',100);p('circle',100)
 for _ in range(3):p('down',30)
 p('circle',100);p('circle',100);vm.shot('spirit-list')
 p('triangle',100);vm.shot('spirit-list-help')
 p('cross');p('square',100);vm.shot('spirit-square')
