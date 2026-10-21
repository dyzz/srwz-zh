from pathlib import Path
import sys,json,hashlib,struct,collections
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'tools'))
from srwz.iso9660 import member_map,scan_iso9660
from srwz.iso_layout import ExecutableOffsetSpec,read_executable_archive_offsets
from srwz.codec import decode_production
from srwz.library import parse_zkn_decoded_chunk
from srwz.library_body_metrics import verify_library_body_metrics
from srwz.library_height_restore import verify_library_height_restore
from special_disc.writeback.migrate_library import raw_fields
sha=lambda b:hashlib.sha256(b).hexdigest()
ids={'library-text/18ab42d7e970fa94','library-text/57961bb5bafe4c92','library-text/b46f1e17643de5c6'}
rows=json.loads((R/'corpus/zh/library/v0.2-reviewed.json').read_text())['entries']
selected={x['source_text_sha256']:x['id'] for x in rows if x['id'] in ids}
batch=json.loads((R/'work/editions/08313d75e7d5cf270f74218b0d84a86cbc236618018dcd923d50b6f5999b1244/original-best-sp.json').read_text())
best={x['member']:x for x in json.loads((R/'config/editions/best/source-layout.json').read_text())['archive_tables']}
original=json.loads((R/'config/library/v0.2.0.json').read_text())['source_member_locks']
sp={'DATA/MTVZKNRT.BIN':0x387160,'DATA/MTVZKNPT.BIN':0x3865b0,'DATA/MTVZKNKW.BIN':0x387770}
report={'status':'three_final_ISOs_native_patch_and_library_fields_read_back','batch':batch['input_digest'],'editions':[]}
for result in batch['results']:
 ed=result['edition_id'];cfg=json.loads((R/f'config/editions/{ed}/edition.json').read_text());name=cfg['executable']['member']
 def reader(p):
  p=R/p;m=member_map(scan_iso9660(p))
  def read(n):
   with p.open('rb') as f:f.seek(m[n].extent_lba*2048);return f.read(m[n].size)
  return read
 native=reader(cfg['source_iso']['path']);final=reader(result['output']['path']);a=native(name);b=final(name)
 records=[];count=0;legacy=[];robot_restores=0
 for member in sp:
  na,fb=native(member),final(member)
  if ed=='original':start=int(original[member]['slps_table_start'],16)
  elif ed=='best':start=best[member]['best_start']
  else:start=sp[member]
  # Offset table has the native document count, plus its terminal entry.
  domain={'DATA/MTVZKNRT.BIN':'robot','DATA/MTVZKNPT.BIN':'character','DATA/MTVZKNKW.BIN':'glossary'}[member]
  n=original[member]['expected_chunk_count']
  if ed=='sp':
   from special_disc.writeback.migrate_library import sp_offsets
   oa=sp_offsets(a,start,len(na));ob=sp_offsets(b,start,len(fb))
  else:
   spec=ExecutableOffsetSpec(domain,member,start,start+4*n)
   oa=read_executable_archive_offsets(a,spec,len(na));ob=read_executable_archive_offsets(b,spec,len(fb))
  assert len(oa)==len(ob)
  for i,(left,right) in enumerate(zip(ob,ob[1:])):
   actual=decode_production(fb[left:right]).output
   fields=dict(raw_fields(actual)[1]);old=parse_zkn_decoded_chunk(decode_production(na[oa[i]:oa[i+1]]).output)
   for tag,data in fields.items():
    if tag not in ('DSCR','DSC2'):continue
    count+=1
    if domain=='robot':
     for prefix in (bytes.fromhex('32 15 34 15 33'),bytes.fromhex('34 15 32 15 33')):
      start_at=0
      while True:
       at=data.find(prefix,start_at)
       if at<0:break
       assert data[at+len(prefix)]==0x8a,(ed,i,tag,'robot restore',data[at:at+7].hex())
       robot_restores+=1;start_at=at+len(prefix)+1
     assert b'\x33\x0a' not in data,(ed,i,tag,'raw LF-valued height operand')
    if bytes.fromhex('32 16 34 16') in data or bytes.fromhex('34 16 32 16') in data:legacy.append([member,i,tag])
   if domain=='character':
    for field in old.fields:
     if field.text is None:continue
     ident=selected.get(sha(field.text.encode()))
     if ident:
      data=fields[field.tag];assert data.startswith(bytes.fromhex('32 15 34 15'))
      records.append(dict(id=ident,document=i,tag=field.tag,sha256=sha(data),lines=len(data.rstrip(b'\0').split(b'\n')),hex=data.hex(' ')))
 assert len(records)==3,(ed,len(records))
 assert not legacy,(ed,legacy)
 assert robot_restores>0,(ed,'no safe robot restore')
 report['editions'].append(dict(edition=ed,iso=result['output'],native_patch=verify_library_body_metrics(b,ed),safe_height_patch=verify_library_height_restore(b,ed),robot_height10_restores=robot_restores,body_fields=count,legacy_22px_baselines=legacy,target_fields=records))
p=R/'docs/issue-assets/native-text-rendering-20261021/safeheight-iso-audit.json';p.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
for row in report['editions']:print(row['edition'],row['body_fields'],'body fields checked;',len(row['target_fields']),'bound targets; old 22px pairs:',len(row['legacy_22px_baselines']))
