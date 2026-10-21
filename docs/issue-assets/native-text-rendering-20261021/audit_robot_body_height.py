"""Read current three-edition candidate ISOs for robot-body height scopes.
Uses actual executable archive offsets and decoded ROBO fields. No ISO writes.
Known native robot profile is height10; height12 restores are a scope mismatch.
Not runtime evidence, not a complete typography or glyph-height acceptance.
"""
from pathlib import Path
import sys,json,hashlib
OUT=Path(__file__).parent;ROOT=OUT.parents[2];sys.path.insert(0,str(ROOT/'tools'))
from srwz.iso9660 import member_map,scan_iso9660
from srwz.iso_layout import ExecutableOffsetSpec,read_executable_archive_offsets
from srwz.codec import decode_production
from srwz.library import parse_zkn_decoded_chunk
from srwz.library_body_metrics import verify_library_body_metrics
from special_disc.writeback.migrate_library import raw_fields,sp_offsets
batch=json.loads((ROOT/'work/editions/07e5d26260a36eae950c92592be2fb3b73b348ebe0d0838242d99367289ff01b/original-best-sp.json').read_text());orig=json.loads((ROOT/'config/library/v0.2.0.json').read_text())['source_member_locks'];best={x['member']:x for x in json.loads((ROOT/'config/editions/best/source-layout.json').read_text())['archive_tables']};member='DATA/MTVZKNRT.BIN';results=[]
for b in batch['results']:
 ed=b['edition_id'];p=ROOT/b['output']['path'];files=member_map(scan_iso9660(p));cfg=json.loads((ROOT/f'config/editions/{ed}/edition.json').read_text());exe_member=cfg['executable']['member']
 def read(name):
  with p.open('rb') as f:f.seek(files[name].extent_lba*2048);return f.read(files[name].size)
 exe=read(exe_member);data=read(member);verify_library_body_metrics(exe,ed)
 if ed=='sp':offsets=sp_offsets(exe,0x387160,len(data))
 else:
  start=int(orig[member]['slps_table_start'],16) if ed=='original' else best[member]['best_start'];count=orig[member]['expected_chunk_count'];offsets=read_executable_archive_offsets(exe,ExecutableOffsetSpec('robot',member,start,start+4*count),len(data))
 fields=0;conflicts=[]
 for index,(left,right) in enumerate(zip(offsets,offsets[1:])):
  decoded=decode_production(data[left:right]).output;kind,raw=raw_fields(decoded);assert kind=='ROBO'
  for tag,payload in raw:
   if tag not in ('DSCR','DSC2'):continue
   fields+=1;counts={f'{height:02X}':payload.count(bytes([0x33,height])) for height in (10,12,13,14)}
   if counts['0C']:conflicts.append({'document':index,'tag':tag,'height_control_counts':counts,'field_sha256':hashlib.sha256(payload).hexdigest()})
 actual_hash=hashlib.sha256()
 with p.open('rb') as stream:
  for chunk in iter(lambda:stream.read(4<<20),b''):actual_hash.update(chunk)
 digest=actual_hash.hexdigest();assert digest==b['output']['sha256'],(ed,'candidate ISO drift')
 results.append({'edition':ed,'iso':b['output']['path'],'iso_sha256':digest,'executable_sha256':hashlib.sha256(exe).hexdigest(),'robot_archive_sha256':hashlib.sha256(data).hexdigest(),'robot_body_native_height':10,'body_fields':fields,'fields_containing_height12':len(conflicts),'scope_mismatch_fields':conflicts});print(ed,fields,'robot body fields;',len(conflicts),'with height12 despite native height10',flush=True)
(OUT/'robot-body-height-audit.json').write_text(json.dumps({'scope':__doc__,'status':'current_candidate_robot_typography_has_confirmed_native_height_scope_mismatch','editions':results},indent=2)+'\n')
