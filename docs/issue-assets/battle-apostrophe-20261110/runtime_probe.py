"""Cold-boot Best, capture a fresh battle, then compare controlled subtitle glyphs.

RAM-injected examples exercise the actual renderer, not their natural voice triggers.
The base state is created from this session's ISO, never reused from an older build.
"""
import sys,json,struct,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'tools/special_disc/writeback')]
from srwz.armsx2_runtime import Armsx2Session
from srwz import armsx2_text_probe as P
from srwz.text import encode_text,two_byte_visible_spaces
from srwz.js_layout import layout_batch
from migrate_slps_text import encoding_tables

iso,card,out=map(lambda s:Path(s).resolve(),sys.argv[1:4]);out.mkdir(parents=True,exist_ok=True)
corpus=json.loads((ROOT/'corpus/zh/battle/srvc-lines.json').read_text())
by={e['id']:e for e in corpus['entries']}
ids=['battle:19705','battle:21251','battle:21270','battle:24719','battle:24510']
ids.append(next(e['id'] for e in corpus['entries'] if 'Thank you very much' in e['translation']))
ids.append(next(e['id'] for e in corpus['entries'] if 'BIG-O' in e['translation']))
cases=[(i,by[i]['translation'].replace('\\n','\n')) for i in ids]
expected=layout_batch([dict(action='measure',scene='battle',text=t,options=dict(typography='proportional',chinesePunctuation='compact')) for _,t in cases])
enc,_,codes,_=encoding_tables();book=P.load_codebook();BUF=0x5fe5b8;CAP=96;results=[]
with Armsx2Session(iso,card,out,renderer='metal',upscale=4) as vm:
 for line in (ROOT/'docs/issue-assets/battle-polish-handoff-20261109/route-main.txt').read_text().splitlines():
  if line.strip() and not line.startswith('#'):vm.cmd(line)
 vm.press('circle',3)
 ready=False
 for n in range(240):
  vm.run(30)
  text=P.decode_line(vm.read_ram(BUF,CAP),book)
  if text.startswith('“'):
   vm.cmd('state probe-base');ready=True;print('fresh battle buffer',repr(text),flush=True);break
  if n%2==0:vm.press('circle',3)
 if not ready:raise RuntimeError('No live battle subtitle buffer after cold route')
 for (identity,t),exp in zip(cases,expected):
  raw=encode_text(two_byte_visible_spaces(t),enc,overrides=codes,terminate=True)
  assert len(raw)<=CAP,(identity,len(raw))
  vm.cmd('load probe-base');vm.cmd(f'poke {BUF:x} '+raw.ljust(CAP,b'\0').hex());vm.run(3)
  vm.cmd('trace 13ab50 name=g s0:20');vm.run(1);trace=out/'glyphs.jsonl';vm.cmd(f'tracedump {trace}');vm.cmd('untrace')
  actual=[]
  for line in trace.read_text().splitlines():
   hit=json.loads(line)
   if 's0' not in hit:continue
   q=struct.unpack('<hhhhHHhh',vm.read_ram(int(hit['s0'],16),20)[:16])
   if 70<=q[3]<=110:actual.append(q)
  rows=[]
  for ri,row in enumerate(exp['result']['rows']):
   want=sorted((g['x'],g['width'],g['height'],g.get('yOffset',0)) for g in row['glyphs'])
   got=sorted((q[2]+160,q[6],q[7],q[3]-84-12*ri) for q in actual if (q[3]-78)//12==ri)
   rows.append(dict(expected=want,actual=got,matches=got==want))
  vm.shot(identity.replace(':','-'))
  results.append(dict(id=identity,text=t,rows=rows,match=all(r['matches'] for r in rows)))
  print(identity,results[-1]['match'],flush=True)
(out/'result.json').write_text(json.dumps(dict(iso=str(iso),cold_boot=True,renderer='metal',upscale=4,evidence_kind='ARMSX2 controlled live subtitle buffer',cases=results),ensure_ascii=False,indent=2)+'\n')
if not all(r['match'] for r in results):raise SystemExit('Runtime glyph mismatch; inspect result.json')
