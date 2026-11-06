import json,sys,struct
from pathlib import Path
R=Path.cwd();sys.path.insert(0,str(R/'tools'))
from srwz.armsx2_runtime import Armsx2Session
from srwz.armsx2_text_probe import trace_commands
iso=R/sys.argv[1];out=(R/sys.argv[2]).resolve()
card=R/'work/analysis/sp-gallery-subtitles-20261013/v7-quality-runtime/save/sp-event-gallery-v7-review.ps2'
nav=['run 1800','press start 3','run 200','press circle 3','run 200','press cross 3','run 180','press down 3','press circle 3','run 240','press up 3','run 30','press circle 3','run 200']
result={'iso':str(iso),'backend':'ARMSX2 sw','cold_boot':True,'ram_injection':False,'state_load':False,'checks':[]}
with Armsx2Session(iso,card,out) as vm:
 for c in nav:vm.cmd(c)
 def capture(label,digits):
  for c in trace_commands('sp'):vm.cmd(c)
  vm.cmd('trace 13b810 name=final_glyph a3:32')
  vm.cmd('trace 13bda8 name=final_xy a3:32')
  vm.run(1);vm.cmd(f'tracedump {out}/{label}-trace.jsonl');vm.cmd('untrace')
  vm.shot(label)
  marker=struct.unpack('<2I',vm.read_ram(0x821be0,8))
  assert marker==(0,0),(label,marker)
  hits=[json.loads(line) for line in (out/f'{label}-trace.jsonl').read_text().splitlines()]
  fractional=[j for j in hits if j['name']=='final_xy' and (int(j['t5'],16)>>16)&15]
  assert len(fractional)==digits,(label,len(fractional))
  assert all((int(j['t5'],16)>>16)&15==8 and (int(j['t1'],16)>>16)&15==0 for j in fractional)
  result['checks'].append({'page':label,'enlarged_digits':len(fractional),'cleared_at_frame_end':True})
 capture('page1',1)
 vm.press('right');vm.run(60);capture('page2',2)
 vm.press('left');vm.run(60);capture('page1-return',1)
 vm.press('cross');vm.run(180);capture('theater',0)
 vm.press('circle');vm.run(180);capture('reenter',1)
(out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
