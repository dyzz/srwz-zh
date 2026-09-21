"""Export SP non-stage text as categorized Markdown and JSON from the current ISO.

Read-only for ISO and corpus. STAGE chunks 1..67 dialogue/events are excluded.
Shared battle subtitles and chapter descriptions are separate appendices.
"""
from __future__ import annotations
import argparse
import collections
import datetime
import hashlib
import json
import re
import struct
import sys
import zipfile
from urllib.parse import quote
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'tools/special_disc/writeback'),str(Path(__file__).parent)]
import export_sd_text as sd
import migrate_compdata as mc
import migrate_library as ml
import migrate_slps_text as mst
import srwz.srvc as srvc
from srwz.codec import decode_production
from srwz.iso9660 import scan_iso9660,member_map
from srwz.text import decode_text
from srwz.library import ZKAN_TEXT_TAGS
from srwz.nisv_strategy_qa import QA_METADATA_GROUPS,_parse_page
from srwz.nisv_tutorial import parse_nisv_tutorial_pages
from srwz.image_export import parse_seg_offsets

from special_disc.source import CURRENT_ISO as ISO
PROPOSAL=ROOT/'work/build/special-disc/text-candidate/font/proposal.json'

def sha(b):return hashlib.sha256(b).hexdigest()
def file_sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
 return h.hexdigest()
def load(p):return json.loads(p.read_text())
def dump(p,d):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
def need(ok,msg):
 if not ok:raise ValueError(msg)
def clean(s):return re.sub(r'[/\\:*?"<>|]','-',s).strip()

class Exporter:
 def __init__(self):
  self.manifest=load(ISO.with_suffix('.json'));need(file_sha(ISO)==self.manifest['iso']['sha256'],'current ISO drift')
  self.members=member_map(scan_iso9660(ISO));self.cache={};self.original=sd.Disc();self.rows={};self.inputs={};self.diagnostics=collections.Counter()
  self.table,_,_,self.readback=mst.encoding_tables(PROPOSAL)
  self.exe=self.member(sd.EXE);self.jp_exe=self.original.original(sd.EXE)
  self.corpus={};self.hash_corpus=collections.defaultdict(list)
  for rel in ['corpus/zh/special-disc/frame-text.json','corpus/zh/special-disc/system-text.json','corpus/zh/special-disc/battle-lines.json','corpus/zh/battle/srvc-lines.json','corpus/zh/story-system-dialogue.json','corpus/zh/menu/stage-names.json']:
   for r in self.input(rel)['entries']:
    self.hash_corpus[r['source_text_sha256']].append((rel,r))
    self.corpus[r['id']]=(rel,r)
    for loc in r.get('locations',[]):
     if isinstance(loc,str):self.corpus[loc]=(rel,r)
  self.component_paths={Path(rel).parent.name:rel for rel in self.manifest['components']}
  for name in ['frame','system','stage','srvc','image-labels']:
   rel=self.component_paths[name];need(file_sha(ROOT/rel)==self.manifest['components'][rel],f'{name} report drift')
  self.frame=self.input(self.component_paths['frame'])
  self.system=self.input(self.component_paths['system'])
  self.bound={r['target']:r for r in self.frame['bindings']}
  self.moved={r['id']:r for r in self.system['tail_shared']}
  self.decoded_cache={}
 def input(self,rel):
  p=ROOT/rel;self.inputs[rel]=file_sha(p);return load(p)
 def member(self,name):
  if name not in self.cache:
   m=self.members[name]
   with ISO.open('rb') as f:f.seek(m.extent_lba*2048);b=f.read(m.size)
   expected=self.manifest['files'].get(name)
   if expected:need(sha(b)==expected,f'{name} member drift')
   self.cache[name]=b
  return self.cache[name]
 def dec(self,name,index,start,jp=False):
  key=(name,index,jp)
  if key not in self.decoded_cache:
   raw=self.original.original(name)if jp else self.member(name);exe=self.jp_exe if jp else self.exe;off=sd.table_offsets(exe,start,len(raw));self.decoded_cache[key]=decode_production(raw[off[index]:off[index+1]]).output
  return self.decoded_cache[key]
 def text(self,data,at=0,jp=False,**kw):return decode_text(data,at,self.table if jp else self.readback,**kw).text
 def add(self,id_,category,source,current,*,changed=None,locations=None,corpus=None,**extra):
  need(id_ not in self.rows,f'duplicate export ID: {id_}')
  binding=corpus or self.corpus.get(id_)
  r=dict(id=id_,category=category,source_text=source,source_text_sha256=sha(source.encode()),translation='',current_text=current,editorial_status='unreviewed',review_translation='',review_notes='',locations=locations or [],**extra)
  if binding:
   path,row=binding
   need(row['source_text_sha256']==r['source_text_sha256'],f'corpus source mismatch: {id_}')
   r.update(corpus_path=path,corpus_id=row['id'],translation=row.get('translation',''),editorial_status=row.get('editorial_status','unreviewed'))
  elif changed:r['translation']=current
  r['status']='语料译文' if binding else '镜像文本，待审校' if changed else '原字节保留，需判定'
  r['flags']=[]
  if re.search('[\u3040-\u30ff]',current):r['flags'].append('镜像仍含假名（含专名或保留原文，需人工判定）')
  if current=='' and source:r['flags'].append('无镜像文本读回')
  if changed is not None:r['bytes_changed']=bool(changed)
  self.rows[id_]=r
 def category(self,c):
  if c.startswith('特别剧场'):return '02-特别剧场/'+c.replace('特别剧场：','')
  if c.startswith('战斗鉴赏'):return '03-战斗鉴赏/'+(c.replace('战斗鉴赏：','')if '：'in c else '其他界面')
  if c in ['弹出通知','ticker']:return '06-系统播报/'+('滚动提示'if c=='ticker'else c)
  if c in ['剧情模式菜单','数据链接','挑战模式','额外关卡菜单说明']:return '05-模式介绍与菜单/'+c
  if c in ['舰船名','机体名','驾驶员名','武器名','特殊能力','BGM 曲名','作品名','用语名']:return '04-共用名称与能力/'+c
  if c=='撤退台词':return '附录B-通用战斗台词/撤退台词'
  return '01-系统界面与帮助/'+c
 def executable(self):
  inv=self.input(str(sd.EXE_STRINGS.relative_to(ROOT)));rows={r['off']:r for group in ['unreferenced','referenced']for r in inv['SD'][group]}
  for at,r in sorted(rows.items()):
   if not any(a<=at<b for a,b in sd.EXE_TEXT_AREAS)or sd.SUSPEND_AREA[0]<=at<sd.SUSPEND_AREA[1]or at in sd.EXE_NOT_TEXT:continue
   source=r['text']
   if not sd.plausible(source,self.table)or self.jp_exe[at-1]!=0:continue
   if self.text(self.jp_exe,at,True)!=source:continue
   if re.fullmatch(r'[ー―－\-\s　０-９0-9％%sd：:（）()＜＞・．.,、一]+',source):continue
   c=next((c for a,b,_,c in sd.EXE_AREAS if a<=at<b),'其他界面')
   if at in sd.EXE_NOTICES:c='弹出通知'
   end=decode_text(self.jp_exe,at,self.table).end
   self.add(f'sd/exe/{at:06X}',self.category(c),source,self.text(self.exe,at),changed=self.jp_exe[at:end]!=self.exe[at:end],locations=[dict(member=sd.EXE,offset=at)],context=sd.EXE_NOTICES.get(at,''))
  pos=sd.SUSPEND_AREA[0];count=0
  while pos<sd.SUSPEND_AREA[1]:
   if self.jp_exe[pos]==0:pos+=1;continue
   speaker=decode_text(self.jp_exe,pos,self.table,stop_at_newline=True)
   if speaker.terminator!='newline' or not speaker.text:pos=self.jp_exe.index(0,pos)+1;continue
   msg=decode_text(self.jp_exe,speaker.end,self.table);now=decode_text(self.exe,pos,self.readback,stop_at_newline=True)
   matches=[x for x in self.hash_corpus[sha(msg.text.encode())]if x[0]=='corpus/zh/story-system-dialogue.json' and x[1].get('editorial_status')=='reviewed']
   self.add(f'sd/suspend/{pos:06X}','02-特别剧场/中断对话正文',msg.text,self.text(self.exe,now.end),changed=self.exe[pos:msg.end]!=self.jp_exe[pos:msg.end],corpus=matches[0]if matches else None,locations=[dict(member=sd.EXE,offset=pos)],speaker_source=speaker.text,speaker_current=now.text)
   pos=msg.end;count+=1
  need(count==296,f'suspend inventory: {count}')
 def compdata(self):
  jp=decode_production(self.original.original('DATA/COMPDATA.BN')).output;now=decode_production(self.member('DATA/COMPDATA.BN')).output
  refs=collections.defaultdict(list)
  for site,at in mc.pointer_targets(jp,sd.COMPDATA_BASE):refs[at].append(site)
  for at,sites in sorted(refs.items()):
   d=mc.text_at(jp,at,self.table)
   if not d or (at and jp[at-1]) or not sd.plausible(d.text,self.table):continue
   region=collections.Counter(mc.region_of(s,2) for s in sites).most_common(1)[0][0]
   _,c=next(((m,c) for a,b,m,c in sd.COMPDATA_AREAS if a<=at<b),sd.COMPDATA_REGION.get(region,('05','其他')))
   if c.startswith('排序键')or region in ['head','pilots']:continue
   id_=f'sd/compdata/{at:05X}';grouped=collections.defaultdict(list)
   for site in sites:
    target=struct.unpack_from('<I',now,site)[0]-sd.COMPDATA_BASE
    need(0<=target<len(now),f'COMPDATA pointer drift {site:X}')
    grouped[target].append(site)
   for n,(target,ps) in enumerate(grouped.items()):
    cat='附录A-关卡外围文字/关卡名称'if c=='关卡名'else self.category(c)
    self.add(id_ if n==0 else id_+f'/variant-{n}',cat,d.text,self.text(now,target),changed=jp[at:d.end]!=now[target:target+d.consumed],locations=[dict(member='DATA/COMPDATA.BN',source_offset=at,offset=target,pointer_sites=ps)],corpus=self.corpus.get(id_))
  for i in range(sd.PILOTS[2]):
   for field,off,size in sd.PILOT_FIELDS:
    at=sd.PILOTS[0]+i*sd.PILOTS[1]+off;source=self.text(jp,at,True,end=at+size)
    if not source:continue
    self.add(f'sd/compdata/pilot/{i:03d}/{field}','04-共用名称与能力/驾驶员名称字段',source,self.text(now,at,end=at+size),changed=jp[at:at+size]!=now[at:at+size],locations=[dict(member='DATA/COMPDATA.BN',offset=at,field=field)])
 def library(self):
  for name,(start,label,_)in sd.ZKN.items():
   jpraw=self.original.original(name);raw=self.member(name);jo=sd.table_offsets(self.jp_exe,start,len(jpraw));no=sd.table_offsets(self.exe,start,len(raw));need(len(jo)==len(no),'library document count drift')
   for i in range(len(jo)-1):
    _,jf=ml.raw_fields(decode_production(jpraw[jo[i]:jo[i+1]]).output);_,nf=ml.raw_fields(decode_production(raw[no[i]:no[i+1]]).output);need([a for a,b in jf]==[a for a,b in nf],'library field drift')
    title=next((self.text(b+b'\0',jp=True) for a,b in jf if a in ['RBTN','CHFN','NAME','WORD','CHNN']),'')
    for (tag,a),(_,b)in zip(jf,nf):
     if tag not in ZKAN_TEXT_TAGS or not a:continue
     source=self.text(a+b'\0',jp=True)
     if not source.strip():continue
     self.add(f'sd/library/{label}/{i:03d}/{tag}','07-资料库/'+sd.ZKN_KIND[label],source,self.text(b+b'\0'),changed=a!=b,locations=[dict(member=name,chunk=i,field=tag)],entry_title=title,field_label=sd.ZKN_TAG.get(tag,tag))
 def nisv(self):
  name='DATA/NISVDATA.BIN';jp=self.dec(name,6,sd.NISV_TABLE,True);now=self.dec(name,6,sd.NISV_TABLE)
  def metadata(data):
   pos=0x476;result=[]
   for group,n in QA_METADATA_GROUPS:
    for i in range(n):end=data.index(0,pos);result.append((group,i,data[pos:end],pos));pos=end+1
   return result
  for (g,i,a,pa),(_,_,b,pb)in zip(metadata(jp),metadata(now)):
   self.add(f'sd/nisv/qa/metadata/{g}/{i:03d}','07-资料库/攻略QA-目录与问题',self.text(a+b'\0',jp=True),self.text(b+b'\0'),changed=a!=b,locations=[dict(member=name,chunk=6,source_offset=pa,offset=pb)],metadata_group=g)
  count,base=struct.unpack_from('<II',jp);need(count==103,'QA count drift')
  for i in range(1,count):
   pages=[]
   for data in [jp,now]:rel,size=struct.unpack_from('<II',data,8+8*i);pages.append(_parse_page(data,base+rel,size))
   a,b=pages;source=sd.qa_lines([(r['y'],self.text(r['raw']+b'\0',jp=True))for r in a['records']]);current=sd.qa_lines([(r['y'],self.text(r['raw']+b'\0'))for r in b['records']])
   self.add(f'sd/nisv/qa/page/{i:03d}','07-资料库/攻略QA-正文',source,current,changed=[r['raw']for r in a['records']]!=[r['raw']for r in b['records']],locations=[dict(member=name,chunk=6,page=i)],positioned_records=[dict(x=r['x'],y=r['y'],text=self.text(r['raw']+b'\0'))for r in b['records']])
  a=parse_nisv_tutorial_pages(self.dec(name,5,sd.NISV_TABLE,True));b=parse_nisv_tutorial_pages(self.dec(name,5,sd.NISV_TABLE))
  for i,(p,q)in enumerate(zip(a,b)):
   self.add(f'sd/nisv/tutorial/{i:02d}','07-资料库/教程',sd.qa_lines([(r['y'],self.text(r['raw']+b'\0',jp=True))for r in p['records']]),sd.qa_lines([(r['y'],self.text(r['raw']+b'\0'))for r in q['records']]),changed=True,locations=[dict(member=name,chunk=5,page=i)])
  a=self.dec(name,4,sd.NISV_TABLE,True);b=self.dec(name,4,sd.NISV_TABLE)
  for i,at in enumerate(range(sd.SQUAD_BASE,len(a)-sd.SQUAD_NAME+1,sd.SQUAD_STRIDE)):
   source=self.text(a,at,True,end=at+sd.SQUAD_NAME)
   if not source:continue
   self.add(f'sd/nisv/squad/{i:03d}','04-共用名称与能力/小队名候选',source,self.text(b,at,end=at+sd.SQUAD_NAME),changed=a[at:at+sd.SQUAD_NAME]!=b[at:at+sd.SQUAD_NAME],locations=[dict(member=name,chunk=4,offset=at)])
 def flow(self):
  jp=decode_production(self.original.original('DATA/STAGE.BIN')).output;now=decode_production(self.member('DATA/STAGE.BIN')).output
  for chart,start,count,ptr in [('SP',0x7510,21,0x74B4),('Z',0x14B20,110,0x14864)]:
   for i in range(count):
    at=start+112*i;parts=[]
    for label,off,size in [('话数',0,16),('标题',16,64)]:
     source=self.text(jp,at+off,True,end=at+off+size);current=self.text(now,at+off,end=at+off+size)
     if not source:continue
     self.add(f'sd/chart/{chart}/{i:03d}/{label}',f'附录A-关卡外围文字/{chart}-流程图话数与标题',source,current,changed=jp[at+off:at+off+size]!=now[at+off:at+off+size],locations=[dict(member='DATA/STAGE.BIN',chunk=0,offset=at+off)])
    p=struct.unpack_from('<I',jp,ptr+4*i)[0]-sd.SD_STAGE_BASE;n=struct.unpack_from('<I',now,ptr+4*i)[0]-sd.SD_STAGE_BASE
    self.add(f'sd/chart/{chart}/{i:03d}/synopsis',f'附录A-关卡外围文字/{chart}-剧情梗概',self.text(jp,p,True),self.text(now,n),changed=jp[p:decode_text(jp,p,self.table).end]!=now[n:decode_text(now,n,self.readback).end],locations=[dict(member='DATA/STAGE.BIN',chunk=0,source_offset=p,offset=n)])
  for r in self.frame['key_help']:
   self.add(r['id'],'01-系统界面与帮助/流程图按键说明',r['source_text'],self.text(now,r['offset']),changed=True,locations=[dict(member='DATA/STAGE.BIN',chunk=0,offset=r['offset'])],translation_source='config/editorial/special-disc/chart-key-help.json')
 def extra_corpus(self):
  framecats={'menu':'05-模式介绍与菜单/其他菜单','group-name':'05-模式介绍与菜单/剧情组名称','narration':'05-模式介绍与菜单/开场与结尾旁白','vt1-page':'05-模式介绍与菜单/模式说明与任务简报','chart-summary':'附录A-关卡外围文字/节点简介','image-label':'08-图片文字/已有文字语料','episode-title':'附录A-关卡外围文字/SP-语料话名','synopsis':'附录A-关卡外围文字/SP-语料梗概','map-legend':'附录A-关卡外围文字/地图名称','squad-name':'附录A-关卡外围文字/编队名称','speaker':'附录A-关卡外围文字/说话人名称'}
  stage=self.input(self.component_paths['stage']);bound=dict(self.bound)
  for c in stage['chunk_reports']:
   for r in c['bindings']:bound[r['target']]=r
  represented={r.get('corpus_id') for r in self.rows.values()}
  for path in ['corpus/zh/special-disc/frame-text.json','corpus/zh/special-disc/system-text.json']:
   for row in self.input(path)['entries']:
    if row['id'] in represented:continue
    locations=row.get('locations',[row['id']]);bindings=[bound[t]for t in locations if isinstance(t,str)and t in bound]
    outputs=list(dict.fromkeys(r['output_text']for r in bindings));current='\n\n'.join(outputs)
    category=framecats[row['category']]if path.endswith('frame-text.json')else self.category(row['category'])
    if row['category']=='vt1-page' and any(str(t).startswith('sd/vt1/50/')for t in locations):category='附录A-关卡外围文字/挑战任务简报'
    if row['category']=='ticker':current=row['translation'];evidence='已核验写回报告：滚动字幕'
    elif row['category']=='image-label':current=row['translation'];evidence='图片文字作者语料；未做 OCR'
    elif bindings:evidence='绑定当前 ISO 的写回报告，按排版输出'
    elif row['id'].startswith(('sd/compdata/','sd/exe/')) and row['id']!='sd/exe/wallpaper-names':
     at=int(row['id'].rsplit('/',1)[1],16);member='DATA/COMPDATA.BN'if '/compdata/'in row['id']else sd.EXE
     data=decode_production(self.member(member)).output if '/compdata/'in row['id']else self.exe
     if row['id']in self.moved:at=int(self.moved[row['id']]['now'],16)
     current=self.text(data,at);locations=[dict(member=member,offset=at)];evidence='当前 ISO 按语料定位回读'
    elif row['id']=='sd/exe/wallpaper-names':current=row['translation'];evidence='模板译文，逐项文本见壁纸名分类'
    else:evidence='仅语料，无独立镜像回读'
    self.add('corpus/'+row['id'],category,row['source_text'],current,corpus=(path,row),locations=locations,evidence=evidence,current_variants=outputs)
 def battle(self):
  srvc.SRVC_MAGIC=0x4F01;name='BTL/SRVC.BIN';jp=self.original.original(name);now=self.member(name);off=parse_seg_offsets(self.original.original('BTL/SRVC.SEG'),len(jp));a=srvc.parse_srvc_archive(jp,off,self.table);b=srvc.parse_srvc_archive(now,off,self.readback)
  groups={};physical=0
  for c,d in zip(a,b):
   need(len(c.records)==len(d.records),'battle record count drift')
   for x,y in zip(c.records,d.records):
    key=(x.text,y.text);physical+=1
    groups.setdefault(key,[]).append(dict(member=name,chunk=x.chunk_index,record=x.record_index,offset=y.archive_text_start,metadata=x.metadata))
  for (source,current),locs in groups.items():
   h=sha(source.encode());matches=[x for x in self.hash_corpus[h]if '/battle/'in x[0]or x[0].endswith('battle-lines.json')];binding=matches[-1]if matches else None
   if binding and binding[0].endswith('special-disc/battle-lines.json'):cat='附录B-通用战斗台词/SP新增台词'
   else:cat=f'附录B-通用战斗台词/本篇复用-{locs[0]["chunk"]//20:02d}'
   self.add('sd/battle/'+h[:16]+'/'+sha(current.encode())[:8],cat,source,current,changed=source!=current,locations=locs,corpus=binding)
  need(physical==59262 and len(groups)==25526,'battle inventory drift');self.diagnostics['battle_physical_records']=physical
 def save(self,out):
  need(not out.exists(),f'output already exists, choose a new --output: {out}')
  out.mkdir(parents=True);groups=collections.defaultdict(list)
  for r in self.rows.values():groups[r['category']].append(r)
  inventory=[]
  for category,rows in sorted(groups.items()):
   rows.sort(key=lambda r:r['id']);rel=Path(*[clean(x)for x in category.split('/')]);p=out/rel
   dump(p.with_suffix('.json'),dict(schema_version=1,category=category,iso=self.manifest['iso'],entries=rows))
   lines=['# '+category,'',f'共 {len(rows)} 条。修改时填写“校订译文”，保留 ID；空白表示未修改。','']
   for i,r in enumerate(rows,1):
    title=r.get('entry_title')or r.get('speaker_current')or ''
    lines += [f'## {i:04d} {title} · `{r["id"]}`','',f'状态：{r["status"]}；审校状态：{r["editorial_status"]}','']
    if r.get('field_label'):lines += ['字段：'+r['field_label'],'']
    for label,key in [('原文','source_text'),('语料／现有译文','translation'),('当前镜像文字','current_text')]:
     lines += ['**'+label+'**','', '````text',r[key],'````','']
    if r['flags']:lines += ['提示：'+'；'.join(r['flags']),'']
    if r.get('evidence'):lines += ['取值依据：'+r['evidence'],'']
    lines += ['**校订译文**','','````text','','````','','**校订备注**','','','<details><summary>定位信息</summary>','','````json',json.dumps(r['locations'],ensure_ascii=False),'````','','</details>','']
   p.with_suffix('.md').write_text('\n'.join(lines)+'\n')
   inventory.append(dict(category=category,entries=len(rows),markdown=str(rel.with_suffix('.md')),json=str(rel.with_suffix('.json')),flagged=sum(bool(r['flags'])for r in rows)))
  total=len(self.rows);main=sum(x['entries']for x in inventory if not x['category'].startswith('附录'));lines=['# SP 非关卡文本分类校对包','',f'生成时间：{datetime.datetime.now().astimezone().isoformat(timespec="seconds")}','',f'主目录 {main:,} 条；含两个附录共 {total:,} 条。条目是文本字段或合并后的通用台词，不等于关卡数。','',f'镜像 SHA-256：`{self.manifest["iso"]["sha256"]}`','', '范围：当前 SP 的系统界面、特别剧场（含中断对话）、战斗鉴赏、名称与能力、模式介绍、系统播报、图鉴、Q&A、教程，以及已有图片文字语料。包含本篇复用内容。','', '关卡话名、梗概、地图名、编队／说话人名、任务简报等外围信息按类单列；流程图内容在附录 A。通用战斗动画台词在附录 B，不混入界面校对。排除 STAGE 1–67 的剧情／挑战对白、事件脚本、关卡胜败条件正文。','', '这是一份现有解析器可定位文本的导出，不是全镜像字符串扫描或位图 OCR。图片中没有文字语料的标签、未识别二进制区域和假名排序键未导出。','', '## 校对方法','', '- Markdown 适合逐类阅读；在每条“校订译文”和“校订备注”下修改。JSON 保留稳定 ID、原文哈希、语料路径与定位，可用于后续受控回写。','- “语料／现有译文”优先取作者语料；无语料且字节已变化时采用镜像文本。当前镜像文字保留排版换行。模板／图片文字及少数报告取值在条目内注明。','- “仍含假名”仅是人工复核提示，不自动认定为漏译；可能包括人名、歌曲名或刻意保留内容。原字节保留也不等于需要翻译。','- 同一句出现在不同用途时保留独立条目；通用战斗台词按原文与当前文字合并，JSON 保留全部触发位置。','- 本工具只导出，不修改语料、ISO 或模拟器配置；导出包不会被构建自动消费。','', '## 分类目录','', '| 类别 | 条目 | 复核提示 | 文件 |','|---|---:|---:|---|']
  for x in inventory:lines.append(f'| {x["category"]} | {x["entries"]} | {x["flagged"]} | [校对稿]({quote(x["markdown"],safe='/')}) · [JSON]({quote(x["json"],safe='/')}) |')
  flags=[dict(id=r['id'],category=r['category'],source_text=r['source_text'],current_text=r['current_text'],flags=r['flags'])for r in self.rows.values()if r['flags']]
  dump(out/'review-flags.json',dict(note='含假名等启发式复核提示，不等于确认漏译。',entries=flags))
  lines += ['',f'另有 {len(flags)} 条启发式提示，见 [复核提示索引](review-flags.json)。这些提示不等于已确认的漏译。','']
  (out/'README.md').write_text('\n'.join(lines)+'\n')
  manifest=dict(schema_version=1,iso=self.manifest['iso'],total_entries=total,main_entries=main,categories=inventory,inputs=self.inputs,members_read={n:sha(b)for n,b in self.cache.items()},excluded=['STAGE chunks 1..67 dialogue/events/conditions','unmapped bitmap text and binary regions','kana sort keys'],diagnostics=dict(self.diagnostics),exporter_sha256=file_sha(Path(__file__)))
  dump(out/'manifest.json',manifest)
  # Independently reread the files, require IDs, counts and original hashes to survive serialization.
  ids=set()
  for x in inventory:
   saved=load(out/x['json'])['entries'];need(len(saved)==x['entries'],'export count mismatch')
   for r in saved:need(r['id']not in ids and sha(r['source_text'].encode())==r['source_text_sha256'],'export identity mismatch');ids.add(r['id'])
  need(ids==set(self.rows),'export omissions');dump(out/'verification.json',dict(status='passed',unique_ids=len(ids),categories=len(inventory),iso_sha256=self.manifest['iso']['sha256'],source_hashes_preserved=True,files={str(p.relative_to(out)):file_sha(p)for p in sorted(out.rglob('*'))if p.is_file()}))
  archive=out.with_suffix('.zip')
  with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED)as z:
   for p in sorted(out.rglob('*')):
    if p.is_file():z.write(p,str(Path(out.name)/p.relative_to(out)))
  print(json.dumps(dict(output=str(out),archive=str(archive),entries=total,main_entries=main,categories=len(inventory)),ensure_ascii=False,indent=2))

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,default=ROOT/'work/review/special-disc/non-stage-text-20260919');args=p.parse_args();e=Exporter()
 for name in ['executable','compdata','library','nisv','flow','extra_corpus','battle']:
  getattr(e,name)();print(name,len(e.rows),flush=True)
 e.save(args.output.resolve())
if __name__=='__main__':main()
