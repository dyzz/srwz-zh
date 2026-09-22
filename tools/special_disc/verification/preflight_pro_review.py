"""Inventory accepted review text against current SP font and fixed-page layouts.

Read-only for corpus and ISO; reports every frame overflow without shortening
accepted prose. Native fields that need a writer stay explicitly unvalidated.
"""
from pathlib import Path
import collections
import hashlib
import json
import struct
import sys
ROOT=Path(__file__).resolve().parents[3]
AREA=ROOT/'work/authoring/special-disc/review-imports/20260919-gpt6-pro'
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'tools/special_disc/writeback')]
import write_frame_text as f
from srwz.codec import decode_production
from srwz.text import decode_text,normalize_original_fullwidth_ascii
from srwz.chinese_layout import fit_chinese_dialogue_layout,rendered_line_width
from srwz.summary import parse_summary
from special_disc.baselines import baseline_iso

def write(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
def main():
 proposal=ROOT/'work/build/special-disc/text-candidate/font/proposal.json';w=f.Writer(baseline_iso('text-canary'),proposal)
 ledger=json.loads((ROOT/'corpus/zh/special-disc/reviewed-non-stage-text.json').read_text())['entries'];native=json.loads((ROOT/'corpus/zh/special-disc/native-text.json').read_text())['entries']
 p=json.loads(proposal.read_text());chars={a['character']for k in ['assignments','surface_alias_assignments','source_compatibility_assignments']for a in p[k]};missing=collections.defaultdict(list)
 for r in ledger:
  for c in set(r['translation']):
   if ord(c)>127 and c!='　'and c not in chars:missing[c].append(r['id'])
 glyphs=[]
 for c,ids in sorted(missing.items()):
  try:encoding=w.encoded(c).hex();error=None
  except ValueError as e:encoding=None;error=str(e)
  glyphs.append(dict(character=c,review_ids=ids,current_encoding=encoding,encoding_error=error,status='outside_verified_font_coverage'))
 issues=[];checked=0;source_flow=decode_production(w.original_member('DATA/STAGE.BIN')).output
 def check(target,limit,fn):
  nonlocal checked
  checked+=1
  try:
   text=fn();encoded=w.encoded(text)
   if limit is not None and len(encoded)>limit:raise ValueError(f'{len(encoded)} encoded bytes exceed {limit}-byte allocation')
  except ValueError as e:issues.append(dict(target=target,corpus_id=w.targets[target]['id'],reason=str(e),translation=w.targets[target]['translation']))
 for target,r in w.targets.items():
  if target.startswith('sd/hsfc/'):
   check(target,None,lambda r=r:fit_chinese_dialogue_layout(r['translation'],profile=w.profiles['sp_hsfc_summary']).text)
  elif target.startswith('sd/flow/synopsis/'):
   i=int(target.rsplit('/',1)[1])-1;at=struct.unpack_from('<I',source_flow,f.sd.FLOW_SYNOPSES[0]+i*4)[0]-f.sd.SD_STAGE_BASE;size=decode_text(source_flow,at,w.table).consumed
   check(target,size,lambda r=r:f.flow_synopsis(r['translation']))
  elif target.startswith('sd/flow/episode/'):
   check(target,64,lambda r=r:r['translation'])
  elif target.startswith('sd/mtzspros/'):
   i=int(target.split('/')[2]);entry=int(target.rsplit('/',1)[1]);raw=w.original_member('DATA/MTZSPROS.BIN');off=f.sd.table_offsets(w.original_exe,f.sd.MTZSPROS_TABLE,len(raw));source=decode_production(raw[off[i]:off[i+1]]).output;e=parse_summary(source,w.table,chunk_index=i).entries[entry]
   width=max(len(line)-len(line.lstrip('　'))+rendered_line_width(line)for line in e.text.split('\n'))
   check(target,None,lambda r=r,e=e,width=width:'\n'.join(f.paragraphs(r['translation'],width,max_lines=len(e.text.split('\n')),protected_terms=('下达',))))
 result=dict(status='engineering_preflight_issues'if glyphs or issues else 'frame_layout_preflight_passed',reviewed_entries=len(ledger),glyphs_outside_verified_coverage=glyphs,unencodable_characters=[r['character']for r in glyphs if r['encoding_error']],frame_fields_checked=checked,frame_issues=issues,native_fields_requiring_writer=len(native),native_categories=dict(collections.Counter(r['category'].split('/')[0]for r in native)),accepted_text_modified=False,iso_modified=False,scope='All accepted character coverage; existing chart summaries, synopses, chart titles and narration layout. This does not validate new native field allocation, image rendering or runtime.')
 write(AREA/'engineering-preflight.json',result)
 print(json.dumps({k:v for k,v in result.items()if k not in ['glyphs_outside_verified_coverage','frame_issues']},ensure_ascii=False,indent=2));print('frame issues',len(issues));print('\n'.join(r['target']+': '+r['reason']for r in issues))
if __name__=='__main__':main()
