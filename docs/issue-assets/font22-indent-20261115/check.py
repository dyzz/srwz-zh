from pathlib import Path
import json
O=Path(__file__).resolve().parent
r=json.loads((O/'runs/best-aligned/report.json').read_text());result={}
for scene in ('story','flow','scroll'):
 s=r['scenes'][scene];assert 'error' not in s,s.get('error');result[scene]={}
 for key,v in s['samples'].items():
  rows=[x for x in v['rows'] if len(x['codes'])>5 and (scene!='story' or x['y']>=61) and (scene!='flow' or x['y']>=-48)][:3]
  assert len(rows)==3,(scene,key)
  starts=[]
  for i,row in enumerate(rows):
   skip=1 if scene=='story' else 0
   if scene=='story':assert row['codes'][0]==(0x9141 if i==0 else 0x93FD)
   starts.append(row['x'][skip])
  assert len(set(starts))==1,(scene,key,starts)
  result[scene][key]={'body_start_x':starts,'y':[x['y'] for x in rows], 'equal':True}
(O/'alignment.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False,indent=2))
