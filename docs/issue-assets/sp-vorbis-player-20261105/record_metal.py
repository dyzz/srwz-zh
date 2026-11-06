from pathlib import Path
import sys,json,struct,time
W=Path(__file__).resolve().parent;R=W.parents[2];sys.path.insert(0,str(R/'tools'))
from srwz.armsx2_runtime import Armsx2Session
commands=[]
for x in map(json.loads,(W.parent/'sp-vocal-20261105/commands.jsonl').read_text().splitlines()):
 if x['reply'][-1]=='OK frame=5000':break
 if x['cmd'].startswith(('run ','press ')):commands.append(x['cmd'])
out=W/'metal4x';addr=json.loads((W/'build-receipt.json').read_text())['symbols']['telemetry'];rows=[]
with Armsx2Session(R/'build/iso/test/sp-vorbis-full.iso',R/'work/feedback/aethersx2-text-dropout-20261002/production-lrps2/sp/save/sp-current.ps2',out,renderer='metal',upscale=4,command_timeout=600) as vm:
 for c in commands:vm.cmd(c)
 vm.shot('configured');vm.press('start',3);vm.run(900);vm.start_video('SP-Z-Gundam-Vorbis-Metal-4x')
 for i in range(12):
  vm.run(300);row={'frame':vm.frame,'t':list(struct.unpack('<32I',vm.read_ram(addr,128)))};rows.append(row);print(row,flush=True)
 path=vm.stop_video();vm.shot('recorded');vm.run(1200);vm.shot('automatic-return');control={'auto_return':list(struct.unpack('<32I',vm.read_ram(addr,128)))};print(control,flush=True)
 (out/'telemetry.json').write_text(json.dumps(rows,indent=2));(out/'control.json').write_text(json.dumps(control,indent=2))
print(path,flush=True)
