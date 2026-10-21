from pathlib import Path
import sys,struct,subprocess,json,importlib.util,concurrent.futures
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'tools'))
from srwz.iso9660 import member_map,scan_iso9660
from srwz.library_optical_metrics import layout
BASE=R/'build/iso/zh-release-original/current-original.iso'
OUT=R/'work/runtime/lrps2/vertical-candidates-20261021'
CASES={'h13-y1':(13,1),'h14-y2':(14,2),'h13-y0':(13,0),'h13-y2':(13,2)}
def prepare(name,h,y):
 p=OUT/name/'candidate.iso';p.parent.mkdir(parents=True,exist_ok=True)
 subprocess.run(['cp','-c',str(BASE),str(p)],check=True)
 m=member_map(scan_iso9660(p))['SLPS_258.87'];s=layout('original');patches=[]
 # Controlled character-only candidate: change decoded optical 8E height14 to13.
 # 8A would also become9; robots are deliberately excluded from this trial.
 if h==13:patches.append((s['base']+28+6*4,0x3041007F,0x2441FF7F))
 if y!=1:patches.append((s['geometry']+12,0x00021400,0x00001021 if y==0 else 0x00021440))
 with p.open('r+b') as f:
  for va,before,after in patches:
   off=m.extent_lba*2048+va-s['delta'];f.seek(off);assert f.read(4)==struct.pack('<I',before)
   f.seek(off);f.write(struct.pack('<I',after))
 (p.parent/'candidate.json').write_text(json.dumps({'scope':'character-only isolated ISO experiment; not production patch','height':h,'record_y_delta':-y,'patches':patches},indent=2))
 return p
def run(name):
 h,y=CASES[name];p=prepare(name,h,y)
 spec=importlib.util.spec_from_file_location('capture_'+name,R/'work/analysis/library-font-fix-20261021/capture_height.py')
 mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
 mod.OUT=OUT/name;mod.ISOS={'original':str(p.relative_to(R))}
 # Existing capture uses one fixed original socket; run sequentially.
 mod.capture('original');print(name,'captured',flush=True)
if __name__=='__main__':
 for name in CASES:run(name)
