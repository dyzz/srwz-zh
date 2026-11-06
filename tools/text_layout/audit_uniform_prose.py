#!/usr/bin/env python3
"""Audit current flow, scroll display groups and compiled library bodies with shared JS.

Read-only: records proposed wraps, source geometry, paragraph/control invariants
and native owner row limits. Does not write corpus, ISO, manifests or website.
"""
import sys,json,collections,hashlib,argparse,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from srwz.js_layout import layout_batch
from srwz.library_typography import library_typography
from srwz.build_layout import library_input
from srwz.chinese_prose import logical_prose_text
from srwz.summary import validate_scroll_placeholders
from srwz.text import CONTROL_NOTATION
parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,default=ROOT/'work/analysis/unified-prose-20261106');args=parser.parse_args()
root=ROOT;out=args.out.resolve();out.mkdir(parents=True,exist_ok=True);os.chdir(ROOT);jobs=[]
paths=['corpus/zh/menu/stage-overviews.json','corpus/zh/summary.json','corpus/zh/special-disc/frame-text.json','corpus/zh/library/v0.2-reviewed.json'];docs={p:json.loads(Path(p).read_text())for p in paths};allrows={r['id']:(p,r)for p,d in docs.items()for r in d['entries']}
records=json.load(open('docs/issue-assets/prose-step-audit-20261026/layout-report.json'))['records']
for r in records:
 members=r['member_ids'];items=[allrows[i]for i in members];text='\n'.join(row['translation']for _,row in items)
 jobs.append(dict(id=r['id'],members=members,path=items[0][0],scene=r['surface'],text=text,options=dict(maxLines=r['maximum_lines'],resourceId=r['id']),maximumRows=r['maximum_lines']))
 if len(members)>1:jobs[-1]['options']['preserveLineCount']=True
for item in docs[paths[-1]]['entries']:
 for tag in item.get('tags',[]):
  if tag not in ['DSCR','DSC2']:continue
  for domain in item.get('domains',[]):
   if domain not in ['character','robot','glossary']:continue
   jobs.append(dict(id=item['id'],tag=tag,members=[item['id']],path=paths[-1],scene='library_'+domain,text=library_input(library_typography(item['translation'],tag,domain=domain)),options={}))
results=[];errors=[]
def paragraphs(text):
 blocks=[]
 for line in text.split('\n'):
  if not line.strip():blocks.append(('blank',line or '　'));continue
  indent=line[:len(line)-len(line.lstrip('　 '))];body=line[len(indent):]
  if blocks and blocks[-1][0]=='paragraph' and not indent:
   blocks[-1]=('paragraph',blocks[-1][1],blocks[-1][2]+body)
  else:blocks.append(('paragraph',indent,body))
 return blocks
for start in range(0,len(jobs),32):
 group=jobs[start:start+32];requests=[]
 for j in group:requests.extend([dict(action='measure',scene=j['scene'],text=j['text'],options=j['options']),dict(scene=j['scene'],text=j['text'],options=j['options'])])
 outputs=layout_batch(requests,timeout=180)
 for k,j in enumerate(group):
  before,after=outputs[2*k:2*k+2]
  if not before['ok']or not after['ok']:
   errors.append(dict(id=j['id'],scene=j['scene'],before=before if not before['ok']else None,after=after if not after['ok']else None));continue
  a,b=before['result'],after['result'];text=b['text'];assert paragraphs(text)==paragraphs(j['text']),(j['id'],'paragraphs changed');assert CONTROL_NOTATION.findall(text)==CONTROL_NOTATION.findall(j['text'])
  assert logical_prose_text(text)==logical_prose_text(j['text']);assert all(r['occupiedPx']<=b['widthPx']for r in b['rows'])
  if 'scroll'in j['scene']:validate_scroll_placeholders(j['text'],text,label=j['id'])
  nonfinal=[r['occupiedPx']for i,r in enumerate(a['rows'][:-1])if r['text'].strip()and a['rows'][i+1]['text'].strip()and not a['rows'][i+1]['text'].startswith(('　',' '))]
  results.append({**j,'after':text,'changed':text!=j['text'],'sourceRows':len(a['rows']),'rows':len(b['rows']),'storedOverwidthRows':sum(r['occupiedPx']>b['widthPx']for r in a['rows']),'capPx':b['widthPx'],'selectedWidthPx':b['selectedWidthPx'],'beforeSpreadPx':max(nonfinal,default=0)-min(nonfinal,default=0),'spreadPx':b['widthSelection']['spreadPx'],'nonfinalWidthsPx':b['widthSelection']['nonfinalWidthsPx']})
 print(min(start+32,len(jobs)),'/',len(jobs),flush=True)
summary={scene:dict(fields=len(group),changed=sum(j['changed']for j in group),storedOverwidthRows=sum(j['storedOverwidthRows']for j in group),spreadImproved=sum(j['spreadPx']<j['beforeSpreadPx']for j in group),spreadEqual=sum(j['spreadPx']==j['beforeSpreadPx']for j in group),spreadWorse=sum(j['spreadPx']>j['beforeSpreadPx']for j in group),withinOnePixel=sum(j['spreadPx']<=1 for j in group),maximumSpreadPx=max(j['spreadPx']for j in group))for scene in sorted(set(j['scene']for j in results))for group in [[j for j in results if j['scene']==scene]]}
report=dict(kind='shared JS source/compiled layout audit, no ISO write or runtime claim',inputs={p:hashlib.sha256(Path(p).read_bytes()).hexdigest()for p in [*paths,'shared/text-layout/engine.mjs','shared/text-layout/contracts.mjs','config/text-layout/native-scene-contracts.json','tools/srwz/build_layout.py']},scanned=len(jobs),passed=len(results),errors=errors,summary=summary,records=results)
(out/'audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(summary,ensure_ascii=False,indent=2));print('errors',errors)
