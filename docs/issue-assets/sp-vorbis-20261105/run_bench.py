from pathlib import Path
import sys,json,struct
W=Path(__file__).resolve().parent;R=W.parents[2];sys.path.insert(0,str(R/'tools'))
from srwz.armsx2_runtime import Armsx2Session
addr=int(next(l.split()[0] for l in (W/'symbols.txt').read_text().splitlines() if l.endswith(' result')),16)
out=W/'runtime-memory';rows=[]
with Armsx2Session(W/'tremor-bench.elf',R/'work/feedback/aethersx2-text-dropout-20261002/production-lrps2/sp/save/sp-current.ps2',out,command_timeout=300) as vm:
 for i in range(20):
  vm.run(120);a=list(struct.unpack('<12I',vm.read_ram(addr,48)));rows.append(dict(frame=vm.frame,result=a));print(rows[-1],flush=True)
  if a[0]==0x564f5242 and a[1] in [3,254,255]:break
 vm.shot('result')
(W/'runtime-memory-result.json').write_text(json.dumps(rows,indent=2)+'\n')
