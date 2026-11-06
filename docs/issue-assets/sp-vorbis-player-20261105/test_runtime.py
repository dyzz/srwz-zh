from pathlib import Path
import sys,json,struct,time
W=Path(__file__).resolve().parent;R=W.parents[2];sys.path.insert(0,str(R/'tools'))
from srwz.armsx2_runtime import Armsx2Session
commands=[]
for x in map(json.loads,(W.parent/'sp-vocal-20261105/commands.jsonl').read_text().splitlines()):
 if x['reply'][-1]=='OK frame=5000':break
 if x['cmd'].startswith(('run ','press ')):commands.append(x['cmd'])
name=sys.argv[1] if len(sys.argv)>1 else 'runtime-01';seconds=int(sys.argv[2]) if len(sys.argv)>2 else 15
out=W/name;addr=json.loads((W/'build-receipt.json').read_text())['symbols']['telemetry'];rows=[]
with Armsx2Session(R/'build/iso/test/sp-vorbis-full.iso',R/'work/feedback/aethersx2-text-dropout-20261002/production-lrps2/sp/save/sp-current.ps2',out,command_timeout=180) as vm:
 for i,c in enumerate(commands):
  vm.cmd(c)
  if i%10==0:print('setup',i,vm.frame,list(struct.unpack('<16I',vm.read_ram(addr,64))),flush=True)
 vm.shot('configured');vm.cmd('audio start');vm.press('start',3)
 for i in range((seconds+4)//5):
  vm.run(300);row=dict(frame=vm.frame,t=list(struct.unpack('<32I',vm.read_ram(addr,128))));rows.append(row);print(row,flush=True);(out/'telemetry.json').write_text(json.dumps(rows,indent=2));vm.shot('battle')
 vm.cmd(f'audio stop {out}/battle.wav');vm.press('cross',3);vm.run(180);vm.shot('returned');control={'returned':list(struct.unpack('<32I',vm.read_ram(addr,128)))};print('returned',control['returned'],flush=True)
 if seconds>=200:
  vm.cmd('audio start');vm.press('start',3);vm.run(900);control['restarted']=list(struct.unpack('<32I',vm.read_ram(addr,128)));vm.cmd(f'audio stop {out}/restarted.wav');vm.shot('restarted');vm.press('cross',3);vm.run(180);control['returned_again']=list(struct.unpack('<32I',vm.read_ram(addr,128)));print(control,flush=True)
 (out/'control.json').write_text(json.dumps(control,indent=2))
