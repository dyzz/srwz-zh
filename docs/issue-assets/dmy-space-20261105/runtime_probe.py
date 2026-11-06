from pathlib import Path
import sys,os,json,hashlib
W=Path(__file__).resolve().parent;R=W.parents[2];sys.path.insert(0,str(R/'tools'))
from srwz.armsx2_runtime import Armsx2Session
iso=Path(sys.argv[1]);name=sys.argv[2];mode=sys.argv[3];out=W/name;out.mkdir(exist_ok=True);os.environ['SRWZ_CD_READ_LOG']=str(out/'cd-reads.csv')
card=R/'work/feedback/aethersx2-text-dropout-20261002/production-lrps2/original/save/current-original.ps2' if mode=='load' else R/'work/runtime/armsx2/quotes-release-20261105/save/Mcd001.ps2'
commands=[]
with Armsx2Session(iso,card,out,runner_dir=W/'probe-runner') as vm:
 def cmd(c):
  x=vm.cmd(c);commands.append(dict(command=c,frame=x.frame,response=x.lines));(out/'commands.json').write_text(json.dumps(commands,indent=2));print(c,x,flush=True);return x
 if mode=='music':
  for c in ['run 1800','press start 3','run 240']+['press down 3']*3+['press circle 3','run 240']+['press down 3']*3+['press circle 3','run 180']:cmd(c)
  for n in range(101):
   cmd('press circle 3');cmd('run 90')
   if n in [0,30,46,99,100]:cmd(f'shot music-{n}');cmd('mem 5585d8 1')
   if n<100:cmd('press down 3');cmd('run 6')
  cmd('press cross 3');cmd('run 180');cmd('shot returned')
 elif mode=='load':
  for c in ['run 1800','press start 3','run 177','press down 3','run 55','press circle 3','run 179','press circle 3','run 800','shot intermission']:cmd(c)
  for _ in range(6):cmd('press down 3');cmd('run 12')
  for c in ['press circle 3','run 500','press circle 3','run 180','shot dialogue']:cmd(c)
  for _ in range(4):
   for c in ['hold r1','press start 3','release r1','run 600']:cmd(c)
  for c in ['shot stage','press circle 3','run 300','press circle 3','run 60','shot unit-menu']:cmd(c)
 elif mode=='new':
  for c in ['run 1600','press start 3','run 120','press circle 12','run 360','press circle 12','run 360','press right 12','run 60','press circle 12','run 120','press down 12','run 8','press down 12','run 8','press down 12','run 8','press circle 12','run 120','press circle 12','run 900','press start 12','run 120','run 600','run 600','shot new-stage','mem 75af54 12']:cmd(c)
  for n in range(10):
   for c in ['press circle 12','run 120','hold r1','press start 12','release r1','run 600']:cmd(c)
   if n in [2,5,9]:cmd(f'shot new-progress-{n}')
 else:raise ValueError(mode)
