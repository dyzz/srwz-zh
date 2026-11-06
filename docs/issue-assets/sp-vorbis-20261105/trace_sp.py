from pathlib import Path
import sys,json,time
W=Path(__file__).resolve().parent;R=W.parents[2];sys.path.insert(0,str(R/'tools'))
from srwz.armsx2_runtime import Armsx2Session
commands=[]
for x in map(json.loads,(W.parent/'sp-vocal-20261105/commands.jsonl').read_text().splitlines()):
 if x['reply'][-1]=='OK frame=5000':break
 if x['cmd'].startswith(('run ','press ')):commands.append(x['cmd'])
out=W/'sp-route-trace'
with Armsx2Session(R/'build/iso/special-disc/sp-current.iso',R/'work/feedback/aethersx2-text-dropout-20261002/production-lrps2/sp/save/sp-current.ps2',out,command_timeout=600) as vm:
 for addr in [0x18cb00,0x18cba0,0x18b270]:vm.cmd(f'trace {addr:x} a1:32 stack')
 for c in commands:vm.cmd(c)
 vm.shot('configured');vm.cmd(f'tracedump {out}/setup.json');vm.cmd('audio start');vm.press('start',3);vm.run(3600);vm.cmd(f'audio stop {out}/battle.wav');vm.shot('battle');vm.cmd(f'tracedump {out}/battle.json');vm.press('cross',3);vm.run(180);vm.shot('returned');vm.cmd(f'tracedump {out}/returned.json')
print('done',flush=True)
