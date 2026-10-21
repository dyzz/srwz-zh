"""Compatibility audit of reserved 33 8A in all three native library archives.
Text fields only; not an audit of story, executable strings, or substitutions.
"""
from pathlib import Path
import sys,json,hashlib
OUT=Path(__file__).parent;ROOT=OUT.parents[2];sys.path.insert(0,str(ROOT/'tools'))
from srwz.iso9660 import member_map,scan_iso9660
from srwz.iso_layout import ExecutableOffsetSpec,read_executable_archive_offsets
from srwz.codec import decode_production
from srwz.library import ZKAN_TEXT_TAGS
from special_disc.writeback.migrate_library import raw_fields,sp_offsets,ARCHIVES
original=json.loads((ROOT/'config/library/v0.2.0.json').read_text())['source_member_locks']
best={r['member']:r for r in json.loads((ROOT/'config/editions/best/source-layout.json').read_text())['archive_tables']}
results=[]
for ed in ('original','best','sp'):
 cfg=json.loads((ROOT/f'config/editions/{ed}/edition.json').read_text());iso=ROOT/cfg['source_iso']['path'];members=member_map(scan_iso9660(iso))
 def read(name):
  row=members[name]
  with iso.open('rb') as f:f.seek(row.extent_lba*2048);return f.read(row.size)
 exe=read(cfg['executable']['member']);assert hashlib.sha256(exe).hexdigest()==cfg['executable']['sha256']
 for member in ARCHIVES:
  data=read(member)
  if ed=='sp':offsets=sp_offsets(exe,ARCHIVES[member][1],len(data))
  else:
   start=int(original[member]['slps_table_start'],16) if ed=='original' else best[member]['best_start'];count=original[member]['expected_chunk_count'];offsets=read_executable_archive_offsets(exe,ExecutableOffsetSpec('native',member,start,start+4*count),len(data))
  conflicts=[];fields=0
  for i,(a,b) in enumerate(zip(offsets,offsets[1:])):
   _,raw=raw_fields(decode_production(data[a:b]).output)
   for tag,payload in raw:
    if tag not in ZKAN_TEXT_TAGS:continue
    fields+=1
    if b'\x33\x8a' in payload:conflicts.append({'document':i,'tag':tag})
  assert not conflicts,(ed,member,conflicts)
  results.append(dict(edition=ed,member=member,archive_sha256=hashlib.sha256(data).hexdigest(),text_fields=fields,reserved_height_occurrences=conflicts))
  print(ed,member,fields,'native text fields: no reserved height operand',flush=True)
(OUT/'native-height-operand-audit.json').write_text(json.dumps(dict(scope=__doc__,status='reserved_operand_absent_in_native_library_fields',archives=results),indent=2)+'\n')
