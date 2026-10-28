"""Differential evidence: shared JS versus Python and captured native samples."""
from pathlib import Path
import sys,json,math,random,argparse,hashlib
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R/'tools'))
from srwz.js_layout import layout_batch
from srwz.chinese_layout import load_layout_profiles,reflow_chinese_dialogue
from srwz.renderer_metrics import text_extent
from srwz.compact_scopes import STORY,BATTLE,FLOW_SYNOPSIS,expand,collapse
from srwz.chinese_prose import reflow_chinese_prose,logical_prose_text
from dataclasses import replace
ap=argparse.ArgumentParser();ap.add_argument('--report',type=Path,default=R/'work/analysis/shared-js-layout-20261028/parity.json');args=ap.parse_args();requests=[];expected=[];inputs={}
p=load_layout_profiles(R/'config/text-layout/zh-layout-profiles.json')
for scene,path,profile in [('story','corpus/zh/story-dialogue/stage-001.json','story_dialogue'),('battle','corpus/zh/battle/srvc-lines.json','battle_subtitle')]:
 raw=(R/path).read_bytes();inputs[path]=hashlib.sha256(raw).hexdigest();rows=json.loads(raw)['entries'];rows=random.Random(2810).sample(rows,min(len(rows),160))
 for row in rows:
  text=row.get('translation','').replace('\\n','\n')
  if not text:continue
  for action in ['measure','layout']:
   try:
    if action=='measure':
     state=None;widths=[]
     for line in text.split('\n'):
      e=text_extent(line,default_advance_px=p[profile].default_advance_px,state=state);state=e.state;widths.append(e.occupied_px)
     value=widths
    else:
     fitted=reflow_chinese_dialogue(text,profile=p[profile]);value={'expectedOwnerRejection':fitted.preserved_reason} if fitted.preserved_reason in ('leading_alignment','separate_quoted_lines') else fitted.text
    requests.append(dict(action=action,text=text,scene=scene,options=dict(preserveLineCount=False)));expected.append(dict(id=row['id'],scene=scene,action=action,value=value))
   except ValueError:pass
for scene,step,metrics in [('story',21,STORY),('battle',22,BATTLE),('main_flow',16,FLOW_SYNOPSIS),('sp_flow',16,FLOW_SYNOPSIS),('main_scroll',24,dict(STORY,letter=12,digit=11,restore_width=24,restore_space=24,restore_height=12)),('sp_scroll',25,dict(STORY,letter=12,digit=11,restore_width=25,restore_space=25,restore_height=12))]:
 for text in ['甲<z>MS-013</z>乙','甲<z>Gundam01</z>乙','<z>013</z>与<z>80%</z>！','<color:03>甲$n乙%03d','<width:0E><space:0C>ABC<width:'+f'{step:02X}'+'><space:'+f'{step:02X}'+'>甲','<z>80%</z>']:
  e=text_extent(expand(text,metrics),default_advance_px=step);requests.append(dict(action='measure',scene=scene,text=text));expected.append(dict(id='mixed:'+text,scene=scene,action='measure',value=[e.occupied_px]))
for scene,path,profile,step,kind in [('main_flow','corpus/zh/menu/stage-overviews.json','stage_scroll_overview',16,None),('sp_flow','corpus/zh/special-disc/frame-text.json','stage_scroll_overview',16,'synopsis'),('main_scroll','corpus/zh/summary.json','world_history_scroll',24,None),('sp_scroll','corpus/zh/special-disc/frame-text.json','sp_narration_scroll',25,'narration')]:
 raw=(R/path).read_bytes();inputs[path]=hashlib.sha256(raw).hexdigest();rows=[r for r in json.loads(raw)['entries']if kind is None or r.get('kind')==kind];rows=random.Random(2810).sample(rows,min(32,len(rows)))
 for row in rows:
  text=row.get('translation','');native=expand(text,FLOW_SYNOPSIS) if scene.endswith('flow') else text
  try:
   fitted=reflow_chinese_prose(native,profile=replace(p[profile],default_advance_px=step));value=collapse(fitted.text,FLOW_SYNOPSIS) if scene.endswith('flow') else fitted.text
   requests.append(dict(action='layout',scene=scene,text=text));expected.append(dict(id=row['id'],scene=scene,action='layout',value=value,new_prose_policy=True))
  except ValueError:pass
responses=layout_batch(requests,timeout=120);failures=[];owner_rejections=[];policy_changes=[];prose_checks=0
for req,want,response in zip(requests,expected,responses):
 actual=response.get('result',{}).get('text') if want['action']=='layout' else [r['occupiedPx']for r in response.get('result',{}).get('rows',[])]
 if want.get('new_prose_policy') and response['ok']:
  result=response['result'];prose_checks+=1
  if (logical_prose_text(req['text'])!=logical_prose_text(result['text']) or not result['valid'] or any(row['occupiedPx']>result['widthPx'] for row in result['rows'])):
   failures.append(dict(**want,input=req['text'],actual=actual,error='new prose policy changed text or exceeded geometry'));continue
  if actual!=want['value']:policy_changes.append(dict(id=want['id'],scene=want['scene'],before=want['value'],after=actual,widthPx=result['widthPx'],widthsPx=[row['occupiedPx']for row in result['rows']]))
  continue
 if isinstance(want['value'],dict) and want['value'].get('expectedOwnerRejection') and response.get('error',{}).get('code')=='owner_contract':
  owner_rejections.append(dict(id=want['id'],reason=want['value']['expectedOwnerRejection']));continue
 if not response['ok']or actual!=want['value']:failures.append(dict(**want,input=req['text'],actual=actual,error=response.get('error')))
report=dict(requests=len(requests),passed=len(requests)-len(failures),equal_results=len(requests)-len(failures)-len(owner_rejections)-len(policy_changes),prose_policy_checks=prose_checks,prose_policy_changes=policy_changes,owner_rejections=owner_rejections,failures=failures,inputs=inputs,scope='Deterministic legacy dialogue/measurement compatibility, intentional new balanced/no-word-protection prose policy checks; not runtime acceptance')
args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:report[k]for k in ['requests','passed']},ensure_ascii=False));print('failures',len(failures));
for f in failures[:8]:print(json.dumps(f,ensure_ascii=False))
raise SystemExit(bool(failures))
