exec(open(__file__.replace('command_cycle_runtime.py','command_runtime.py')).read().split('events=[]')[0])
from srwz.armsx2_runtime import Armsx2Session
out=R/f'work/runtime/armsx2/native-command-20261106/{ed}-cycle'
with Armsx2Session(iso,card,out,renderer='metal',upscale=4) as vm:
 def p(b,n=60):vm.press(b);vm.run(n)
 vm.run(1800);p('start',180);p('down');p('down');p('circle',500)
 for i in range(8):
  p('r1',100);p('circle',100);vm.shot(f'command-{i}');p('cross');print(i,flush=True)
