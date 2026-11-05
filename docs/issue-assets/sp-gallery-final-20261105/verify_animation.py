import sys,json,struct,hashlib,concurrent.futures
from pathlib import Path
R=Path.cwd();sys.path.insert(0,str(R/'tools'))
from srwz.armsx2_runtime import Armsx2Session
iso=R/'build/iso/special-disc/sp-current.iso';root=R/'work/analysis/sp-showtime-o-align-20261105/animations'
card=R/'work/analysis/sp-gallery-subtitles-20261013/v7-quality-runtime/save/sp-event-gallery-v7-review.ps2'
nav=['run 1800','press start 3','run 200','press circle 3','run 200','press cross 3','run 180','press down 3','press circle 3','run 240','press up 3','run 30','press circle 3','run 200']
def test(case):
 row,button=case;out=root/f'{row}-{button}';out.mkdir(parents=True,exist_ok=True)
 with Armsx2Session(iso,card,out) as vm:
  for c in nav:vm.cmd(c)
  if row>=11:vm.press('right');vm.run(30)
  for _ in range(row%11):vm.press('down');vm.run(5)
  vm.shot('selected')
  before=vm.read_ram(0x5a5080,0x76940)
  vm.cmd('watch 821f00 16');vm.press(button)
  states=[];started=False
  for elapsed in range(0,18000,60):
   vm.run(60);state=struct.unpack('<4I',vm.read_ram(0x821f00,16));states.append([elapsed+60,*state])
   if state[1] in [1,2]:started=True;assert state[0]==row,state
   if elapsed in [240,540,1140,1740,2940,4740,7140]:vm.shot(f'play-{elapsed+60}')
   if started and state[1]==0:
    assert state[2]==row,state
    vm.shot('returned');break
  else:raise AssertionError('animation did not return')
  after=vm.read_ram(0x5a5080,0x76940)
  assert before==after, 'roster not restored'
  result=dict(row=row,mode=button,backend='ARMSX2 sw',cold_boot=True,ram_injection=False,state_load=False,elapsed_frames=elapsed+60,roster_restored=True,roster_sha256=hashlib.sha256(after).hexdigest(),states=states)
  (out/'result.json').write_text(json.dumps(result,indent=2))
 return {k:v for k,v in result.items() if k!='states'}
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as p:
 results=list(p.map(test,[(1,'circle'),(1,'triangle'),(18,'circle'),(18,'triangle')]))
(root/'results.json').write_text(json.dumps(results,indent=2));print(json.dumps(results))
