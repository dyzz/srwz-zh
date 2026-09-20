"""Filter a verified non-stage export against original main-game text.

Exact source hashes and layout-only normalization remove reused text, regardless
of its translation status. Keep modified sentences intact. Never alter corpus/ISO.
"""
from __future__ import annotations
import argparse
import collections
import json
import re
import struct
import zipfile
from pathlib import Path
import export_non_stage_text as full
from srwz.text import normalize_original_fullwidth_ascii,load_text_table,decode_text
from srwz.iso_layout import ExecutableOffsetSpec,read_executable_archive_offsets
from srwz.nisv_strategy_qa import QA_METADATA_GROUPS,_parse_page
from srwz.nisv_tutorial import parse_nisv_tutorial_pages

ROOT=full.ROOT

def normalized(text):
 return re.sub(r'\s+','',normalize_original_fullwidth_ascii(text.replace('\\n','\n')))

class MainIndex:
 def __init__(self):self.exact={};self.layout={};self.inputs={};self.table=load_text_table(full.mc.TABLE)
 def read(self,path):
  data=path.read_bytes();self.inputs[str(path.relative_to(ROOT))]=full.sha(data);return data
 def add(self,text,where):
  if not isinstance(text,str)or not text.strip():return
  self.exact.setdefault(full.sha(text.encode()),where);self.layout.setdefault(full.sha(normalized(text).encode()),where)
 def text(self,data,at=0):return decode_text(data,at,self.table).text
 def corpus(self):
  def visit(d,where):
   if isinstance(d,dict):
    h=d.get('source_text_sha256')or d.get('source_sha256')
    if isinstance(h,str)and re.fullmatch('[0-9a-f]{64}',h):self.exact.setdefault(h,where+':'+str(d.get('id','')))
    for k,v in d.items():
     if k.endswith('by_source_text') and isinstance(v,dict):
      for source in v:self.add(source,where+':'+k)
     if k in ['source','source_text','japanese']and isinstance(v,str):self.add(v,where+':'+str(d.get('id','')))
     elif isinstance(v,(dict,list)):visit(v,where)
   elif isinstance(d,list):
    for x in d:visit(x,where)
  for p in sorted((ROOT/'corpus/zh').rglob('*.json')):
   if 'special-disc'in p.parts:continue
   visit(json.loads(self.read(p)),str(p.relative_to(ROOT)))
 def disc(self):
  disc=ROOT/'work/disc';exe=self.read(disc/'SLPS_258.87')
  inventory=json.loads(self.read(full.sd.EXE_STRINGS))
  for group in ['referenced','unreferenced']:
   for r in inventory['OG'][group]:
    self.add(r['text'],f'Original EXE 0x{r["off"]:X}')
    if r['text']=='第%s話『':
     for number in range(1,61):self.add(f'第{number}話',f'Original EXE episode-label template 0x{r["off"]:X}')
  cd=full.decode_production(self.read(disc/'DATA/COMPDATA.BN')).output
  for site,at in full.mc.pointer_targets(cd,full.mc.OG_BASE):
   t=full.mc.text_at(cd,at,self.table)
   if t:self.add(t.text,f'Original COMPDATA 0x{at:X}')
  for i in range(full.mc.OG_PILOTS[2]):
   for field,off,size in full.mc.PILOT_FIELDS:
    at=full.mc.OG_PILOTS[0]+i*full.mc.OG_PILOTS[1]+off
    self.add(decode_text(cd,at,self.table,end=at+size).text,f'Original pilot {i}/{field}')
  for member,((start,end),_)in full.ml.ARCHIVES.items():
   raw=self.read(disc/member);spec=ExecutableOffsetSpec(name=member,member=member,table_start=start,table_end=end);offs=read_executable_archive_offsets(exe,spec,len(raw))
   for i,(a,b)in enumerate(zip(offs,offs[1:])):
    _,fields=full.ml.raw_fields(full.decode_production(raw[a:b]).output)
    for tag,data in fields:
     if tag in full.ZKAN_TEXT_TAGS:self.add(self.text(data+b'\0'),f'Original {member}/{i}/{tag}')
  raw=self.read(disc/'DATA/NISVDATA.BIN');spec=ExecutableOffsetSpec(name='NISV',member='DATA/NISVDATA.BIN',table_start=0x328E90,table_end=0x328EAC);offs=read_executable_archive_offsets(exe,spec,len(raw))
  qa=full.decode_production(raw[offs[6]:offs[7]]).output;pos=0x476
  for group,n in QA_METADATA_GROUPS:
   for i in range(n):end=qa.index(0,pos);self.add(self.text(qa[pos:end]+b'\0'),f'Original QA {group}/{i}');pos=end+1
  count,base=struct.unpack_from('<II',qa)
  for i in range(1,count):
   at,size=struct.unpack_from('<II',qa,8+8*i);page=_parse_page(qa,base+at,size)
   self.add(full.sd.qa_lines([(r['y'],self.text(r['raw']+b'\0'))for r in page['records']]),f'Original QA page {i}')
  for i,page in enumerate(parse_nisv_tutorial_pages(full.decode_production(raw[offs[5]:offs[6]]).output)):
   self.add(full.sd.qa_lines([(r['y'],self.text(r['raw']+b'\0'))for r in page['records']]),f'Original tutorial page {i}')
  sq=full.decode_production(raw[offs[4]:offs[5]]).output
  for i,at in enumerate(range(full.sd.SQUAD_BASE,len(sq)-full.sd.SQUAD_NAME+1,full.sd.SQUAD_STRIDE)):
   self.add(decode_text(sq,at,self.table,end=at+full.sd.SQUAD_NAME).text,f'Original squad name {i}')
  names=self.read(disc/'MAP/MAPNAME.BIN')
  for at in range(0,len(names),256):self.add(self.text(names,at),f'Original map name {at//256}')
  flow=full.decode_production(self.read(disc/'DATA/STAGE.BIN')).output
  for i in range(110):
   at=struct.unpack_from('<I',flow,0x10DD4+4*i)[0]-0x7566F0
   self.add(self.text(flow,at),f'Original chart overview {i}')
  # Extract known main-game SRVC subtitles as source, independent of translated corpus coverage.
  raw=self.read(disc/'BTL/SRVC.BIN');seg=self.read(disc/'BTL/SRVC.SEG');full.srvc.SRVC_MAGIC=0x4F00
  for c in full.srvc.parse_srvc_archive(raw,full.parse_seg_offsets(seg,len(raw)),self.table):
   for r in c.records:self.add(r.text,f'Original SRVC {r.chunk_index}/{r.record_index}')
 def match(self,row):
  h=row['source_text_sha256']
  if h in self.exact:return 'exact_source',self.exact[h]
  h=full.sha(normalized(row['source_text']).encode())
  if h in self.layout:return 'layout_only',self.layout[h]
  if row['id'].startswith('sd/chart/Z/'):return 'main_game_chart','SP copy of main-game chart'
  return None

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--input',type=Path,default=ROOT/'work/review/special-disc/non-stage-text-20260919');parser.add_argument('--output',type=Path,default=ROOT/'work/review/special-disc/sp-only-non-stage-text-20260919');args=parser.parse_args()
 src=args.input.resolve();out=args.output.resolve();full.need(not out.exists(),'output already exists; choose another --output')
 previous=full.load(src/'manifest.json');verified=full.load(src/'verification.json')
 for f,h in verified['files'].items():full.need(full.file_sha(src/f)==h,f'input export edited: {f}; preserve edits before regenerating')
 rows=[r for c in previous['categories']for r in full.load(src/c['json'])['entries']]
 idx=MainIndex();idx.corpus();idx.disc();kept={};removed=[]
 for r in rows:
  match=idx.match(r)
  if match:removed.append(dict(id=r['id'],category=r['category'],source_text_sha256=r['source_text_sha256'],reason=match[0],main_game_reference=match[1]))
  else:r['scope']='SP 新增或修改：未在本篇原文索引中匹配';kept[r['id']]=r
 full.need(len(kept)+len(removed)==len(rows),'filter accounting failed')
 full.need(all(idx.match(r)is None for r in kept.values()),'known reused text remains')
 exporter=full.Exporter.__new__(full.Exporter);exporter.manifest={'iso':previous['iso']};exporter.rows=kept;exporter.inputs={**previous['inputs'],**idx.inputs};exporter.cache={};exporter.diagnostics=collections.Counter(input_entries=len(rows),excluded_main_game_entries=len(removed));exporter.save(out)
 report=dict(input_export=str(src.relative_to(ROOT)),input_manifest_sha256=full.file_sha(src/'manifest.json'),input_entries=len(rows),kept_entries=len(kept),excluded_entries=len(removed),exclusion_reasons=dict(collections.Counter(r['reason']for r in removed)),matching='Original source hash; or identical after whitespace/newline/fullwidth-ASCII normalization. No fuzzy substring or translation matching.',main_game_exact_hashes=len(idx.exact),main_game_normalized_hashes=len(idx.layout),excluded=removed)
 # Evidence lives outside the reader package, so the package contains only retained text.
 evidence=out.parent/(out.name+'-filter-evidence.json');full.dump(evidence,report)
 p=out/'README.md';text=p.read_text().replace('# SP 非关卡文本分类校对包','# SP 新增／修改非关卡文本分类校对包').replace('包含本篇复用内容。','本篇已有原文已排除，仅保留 SP 新增或修改的内容。').replace('当前 SP 的系统界面、特别剧场（含中断对话）、战斗鉴赏、名称与能力、模式介绍、系统播报、图鉴、Q&A、教程，以及已有图片文字语料。','当前 SP 新增或修改的界面、特别剧场、战斗鉴赏、名称、模式介绍、系统播报、图鉴、Q&A，以及已有图片文字语料。')
 text=text.replace('## 校对方法',f'本轮从 {len(rows):,} 条中排除本篇已有的 {len(removed):,} 条，保留 {len(kept):,} 条。判断依据是本篇原盘和语料的日文原文；仅换行、空白或全角英数字形式不同也排除。句子内容实际改动的保留完整原文，不做模糊匹配删除。译文是否已完成不影响是否保留。\n\n## 校对方法')
 p.write_text(text)
 m=full.load(out/'manifest.json');m.update(scope='SP-only new or modified non-stage text',filter_script_sha256=full.file_sha(Path(__file__)),filter_evidence=dict(path=str(evidence.relative_to(ROOT)),sha256=full.file_sha(evidence)),main_game_removed=len(removed));m['members_read']=previous['members_read'];m['excluded'].append('all indexed original main-game source text, including layout-only variants');full.dump(out/'manifest.json',m)
 v=full.load(out/'verification.json');v.update(scope_filter_verified=True,input_count_balanced=True,files={str(p.relative_to(out)):full.file_sha(p)for p in sorted(out.rglob('*'))if p.is_file()and p.name!='verification.json'});full.dump(out/'verification.json',v)
 with zipfile.ZipFile(out.with_suffix('.zip'),'w',zipfile.ZIP_DEFLATED)as z:
  for p in sorted(out.rglob('*')):
   if p.is_file():z.write(p,str(Path(out.name)/p.relative_to(out)))
 print(json.dumps(dict(kept=len(kept),removed=len(removed),main_entries=m['main_entries'],categories=len(m['categories']),reasons=report['exclusion_reasons']),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
