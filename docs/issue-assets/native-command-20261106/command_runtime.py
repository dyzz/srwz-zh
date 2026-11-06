import sys,json,hashlib
from pathlib import Path
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'tools'))
from srwz.armsx2_runtime import Armsx2Session
ed=sys.argv[1];scenario_ed='original' if ed=='best' else ed
s=json.loads((R/f'docs/issue-assets/menu-native-restore-20261003/{scenario_ed}-runtime-scenario.json').read_text());card=R/('work/runtime/lrps2/native-font-resources-20261021/sp/save/Super Robot Taisen Z - Special Disc [J].ps2' if ed=='sp' else 'work/verification/spirit-cost-production-20261010/best-cold/save/current-best.ps2');iso=R/f'build/iso/native-command-20261106/{ed}.iso';out=R/f'work/runtime/armsx2/native-command-20261106/{ed}'
events=[]
for a in s['actions']:events.extend([(a['frame'],'hold',a['button']),(a['frame']+a['duration_frames'],'release',a['button'])])
for c in s['captures']:events.append((c['frame'],'shot',c['id']))
# Observe the affected map menu immediately after continuing, before opening the roster.
events.extend([(2450,'shot','continued-map'),(2535,'shot','map-command')])
shots=[];before=hashlib.sha256(card.read_bytes()).hexdigest()
with Armsx2Session(iso,card,out,renderer='metal',upscale=4) as vm:
 for frame,op,arg in sorted(events):
  if frame>vm.frame:vm.run(frame-vm.frame)
  if op=='shot':shots.append(dict(frame=vm.frame,name=arg,path=str(vm.shot(arg))));print(ed,arg,vm.frame,flush=True)
  else:vm.cmd(f'{op} {arg}')
 if vm.frame<s['terminal_frame']:vm.run(s['terminal_frame']-vm.frame)
assert hashlib.sha256(card.read_bytes()).hexdigest()==before
(out/'receipt.json').write_text(json.dumps(dict(evidence_kind='ARMSX2-runner',renderer='metal',upscale=4,iso=str(iso),source_card_sha256=before,source_card_unchanged=True,shots=shots,status='captured_requires_visual_review'),indent=2))
