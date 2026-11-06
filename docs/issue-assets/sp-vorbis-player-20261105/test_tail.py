from pathlib import Path
import sys,json,struct,time
W=Path(__file__).resolve().parent;R=W.parents[2];sys.path.insert(0,str(R/'tools'))
from srwz.armsx2_runtime import Armsx2Session
commands=[]
for x in map(json.loads,(W.parent/'sp-vocal-20261105/commands.jsonl').read_text().splitlines()):
 if x['reply'][-1]=='OK frame=5000':break
 if x['cmd'].startswith(('run ','press ')):commands.append(x['cmd'])
out=W/'tail-loop';addr=json.loads((W/'build-receipt.json').read_text())['symbols']['telemetry'];rows=[]
with Armsx2Session(R/'build/iso/test/sp-vorbis-full.iso',R/'work/feedback/aethersx2-text-dropout-20261002/production-lrps2/sp/save/sp-current.ps2',out,command_timeout=180) as vm:
 for c in commands:vm.cmd(c)
 vm.press('start',3);vm.run(180);vm.cmd(f'poke {addr+27*4:x} b4000000');vm.cmd('audio start')
 for i in range(12):
  vm.run(300);row={'frame':vm.frame,'t':list(struct.unpack('<32I',vm.read_ram(addr,128)))};rows.append(row);print(row,flush=True)
 vm.cmd(f'audio stop {out}/battle.wav');vm.shot('looped');vm.press('cross',3);vm.run(180);control={'returned':list(struct.unpack('<32I',vm.read_ram(addr,128)))};vm.shot('returned');vm.cmd('audio start');vm.press('start',3);vm.run(900);control['restarted']=list(struct.unpack('<32I',vm.read_ram(addr,128)));vm.cmd(f'audio stop {out}/restarted.wav');vm.shot('restarted');vm.press('cross',3);vm.run(180);control['returned_again']=list(struct.unpack('<32I',vm.read_ram(addr,128)));print(control,flush=True)
 (out/'telemetry.json').write_text(json.dumps(rows,indent=2));(out/'control.json').write_text(json.dumps(control,indent=2))
