"""Project stored prose/battle owners with native source row budgets, without writes to corpus."""
from pathlib import Path
import argparse
import hashlib
import json
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from srwz.js_layout import layout_batch
from srwz.build_layout import runtime_inputs

def prepare(output):
 import build_full_story_components as b
 config=json.loads((ROOT/'config/full-story-components.json').read_text())['world_history']
 raw=(ROOT/config['original']['path']).read_bytes();elf=(ROOT/config['original_slps']['path']).read_bytes()
 offsets=b.read_executable_archive_offsets(elf,b.CORE_ARCHIVE_SPECS['MTV_PROS.BIN'],len(raw))
 table=b.load_text_table(ROOT/'vendor/upstream-python/project/tbl_all.json');limits={}
 for i,(start,end) in enumerate(zip(offsets,offsets[1:])):
  for entry in b.parse_summary(b.decode(raw[start:end]).output,table,chunk_index=i).entries:
   limits[entry.entry_id]=(len(entry.text.split('\n')),hashlib.sha256(entry.text.encode()).hexdigest())
 output.mkdir(parents=True,exist_ok=False)
 report=dict(complete=False,inputs=runtime_inputs(),files=[])
 for relative,scene in [('corpus/zh/menu/stage-overviews.json','main_flow'),('corpus/zh/summary.json','main_scroll'),('corpus/zh/battle/srvc-lines.json','battle')]:
  source=(ROOT/relative).read_bytes();document=json.loads(source);rows=[r for r in document['entries'] if r.get('translation')]
  batch=128 if scene=='battle' else 8
  for start in range(0,len(rows),batch):
   group=rows[start:start+batch];requests=[]
   for row in group:
    options=dict(typography='proportional',chinesePunctuation='compact',escapedNewlines='\\n' in row['translation'])
    if scene=='main_scroll':
     count,source_hash=limits[row['id']]
     if source_hash!=row['source_text_sha256']:raise ValueError('Scroll source binding drift')
     options.update(maxLines=count,resourceId=row['id'])
    requests.append(dict(scene=scene,text=row['translation'],options=options))
   for row,response in zip(group,layout_batch(requests,timeout=120)):
    if not response['ok']:raise ValueError((row['id'],response['error']))
    row['translation']=response['result']['text']
   print(scene,start+len(group),'/',len(rows),flush=True)
  destination=output/relative;destination.parent.mkdir(parents=True,exist_ok=True)
  destination.write_text(json.dumps(document,ensure_ascii=False,indent=2)+'\n')
  report['files'].append(dict(source=relative,sourceSha256=hashlib.sha256(source).hexdigest(),candidate=relative,candidateSha256=hashlib.sha256(destination.read_bytes()).hexdigest()))
 report['complete']=True
 (output/'receipt.json').write_text(json.dumps(report,indent=2)+'\n')
 return report

if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
 prepare(parser.parse_args().output)
