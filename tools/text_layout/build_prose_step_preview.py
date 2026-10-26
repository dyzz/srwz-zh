#!/usr/bin/env python3
"""Materialize a reviewed fixed-step report into independent test ISOs.

Preserves decoded STAGE text allocations; relocates archives when compressed
slots grow, updating the native offset table, file catalog and UDF together.
Preserves bytes outside the declared archive/offset-table/catalog changes and compressed
STAGE-0 and prose chunk slots. Existing native metric controls implement Latin
compaction; this does not claim a new automatic parser patch. No corpus or
production manifest is changed. Source/native slot and decoded readback checks
must all finish before an ISO is cloned.
"""
from dataclasses import replace
from pathlib import Path
import argparse,hashlib,json,os,re,struct,subprocess,sys
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'tools/special_disc/writeback')]
from srwz.text import CONTROL_NOTATION,encode_text,decode_text,normalize_original_fullwidth_ascii
from srwz.compact_scopes import FLOW_SYNOPSIS
from srwz.renderer_metrics import COMPACT_VISIBLE_RUN
from srwz.codec import decode_production,reencode_changed_suffix
from srwz.iso9660 import member_map,scan_iso9660
from srwz.iso_layout import CORE_ARCHIVE_SPECS,read_executable_archive_offsets
from srwz.stage_overview import parse_stage_overviews
from srwz.summary import parse_summary,validate_scroll_placeholders
from special_disc.iso_relocation import append_members,verify_relocation
from migrate_slps_text import encoding_tables

def digest(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()

def compile_compaction(text,scene):
 """Select existing native metric controls without editing author notation."""
 w=scene['width'];h=scene['height'];step=scene['step_x'];explicit=False;parts=[];i=0
 while i<len(text):
  match=CONTROL_NOTATION.match(text,i)
  if match:
   raw=match.group();parts.append(raw);tag=re.fullmatch(r'<(width|space|height):([0-9A-Fa-f]{2})>',raw)
   if tag:
    value=int(tag[2],16)
    if tag[1]=='width':w=value
    elif tag[1]=='space':step=value
    else:h=value&0x7f if 0x8a<=value<=0x8e else value;explicit=True
   i=match.end();continue
  end=i+1
  while end<len(text) and not CONTROL_NOTATION.match(text,end):end+=1
  chunk=text[i:end]
  if (w,h,step)==(scene['width'],scene['height'],scene['step_x']):
   for run in reversed(list(COMPACT_VISIBLE_RUN.finditer(normalize_original_fullwidth_ascii(chunk)))):
    metrics=dict(FLOW_SYNOPSIS) if scene['flow'] else dict(width=scene['compact_width'],space=scene['compact_step'],letter=h,digit=h if explicit else h-1,restore_width=w,restore_space=step,restore_height=h)
    value=chunk[run.start():run.end()];payload=[];active=None
    for character in value:
     digit=character.isascii() and character.isdigit() or '０'<=character<='９'
     selected=metrics['digit' if digit else 'letter']
     if selected!=active:
      payload.append(f'<height:{selected:02X}>');active=selected
     payload.append(character)
    restore=f'<space:{step:02X}><width:{w:02X}>' if value.endswith(('%','％')) else f'<width:{w:02X}><space:{step:02X}>'
    compiled=f'<width:{metrics["width"]:02X}><space:{metrics["space"]:02X}>'+''.join(payload)+restore+f'<height:{metrics["restore_height"]:02X}>'
    chunk=chunk[:run.start()]+compiled+chunk[run.end():]
  parts.append(chunk);i=end
 return ''.join(parts)

def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--report',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);ap.add_argument('--editions',nargs='+',default=['original','best','sp']);args=ap.parse_args();args.out.mkdir(parents=True,exist_ok=True)
 report=json.loads(args.report.read_text());assert not report['failures'];os.environ['RUSTC_WRAPPER']=''
 snapshot=args.out/'layout-report.json'
 if snapshot.exists():assert snapshot.read_bytes()==args.report.read_bytes(),'Reviewed layout report changed'
 else:snapshot.write_bytes(args.report.read_bytes())
 table,_,codes,readback=encoding_tables(ROOT/'work/build/special-disc/text-candidate/font/proposal.json')
 # Runtime decoding uses the installed glyph/code aliases.
 prepared={};all_receipts=[]
 for record in report['records']:
  for key,value in record['field_replacements'].items():
   compiled=compile_compaction(value,record['scene_metrics']).replace(' ','　')
   prepared[key]=compiled
 (args.out/'compiled-text.json').write_text(json.dumps(prepared,ensure_ascii=False,indent=2)+'\n')
 for ed in args.editions:
  cfg=json.loads((ROOT/f'config/editions/{ed}/edition.json').read_text());manifest=json.loads((ROOT/f'manifests/editions/{ed}/current.json').read_text());base=ROOT/manifest['output']['path'];assert digest(base)==manifest['output']['sha256']
  source=ROOT/cfg['source_iso']['path'];bm=member_map(scan_iso9660(base));sm=member_map(scan_iso9660(source));patches=[];checks=[]
  def member(path,mm,name):
   entry=mm[name]
   with path.open('rb') as f:f.seek(entry.extent_lba*2048);return f.read(entry.size)
  native_exe=member(source,sm,cfg['executable']['member']);current_exe=member(base,bm,cfg['executable']['member'])
  native_stage=member(source,sm,'DATA/STAGE.BIN');current_stage=member(base,bm,'DATA/STAGE.BIN');hb=member(base,bm,'HEDBDY/HB.BIN');slot=struct.unpack_from('<I',hb,(0x5170 if ed=='sp' else 30320)+4)[0]
  original=decode_production(current_stage[:slot]);data=bytearray(original.output);native=decode_production(native_stage).output
  if ed=='sp':
   slots=[]
   for k in range(21):
    at=struct.unpack_from('<I',native,0x74b4+4*k)[0]-0x8045f0;capacity=decode_text(native,at,table).consumed;slots.append((f'synopsis/{k:03d}',at,capacity))
  else:slots=[(e.entry_id,e.text_offset,e.encoded_size) for e in parse_stage_overviews(native,table,base_address=int(cfg['layout']['stage_base'],16))]
  for key,at,capacity in slots:
   raw=encode_text(prepared[key],table,overrides=codes,terminate=True);assert len(raw)<=capacity,(ed,key,len(raw),capacity)
   data[at:at+capacity]=raw.ljust(capacity,b'\0');checks.append(dict(id=key,encoded=len(raw),capacity=capacity,decoded_offset=at))
   # Compare encoded bytes, including all metric controls, after decoding.
   assert bytes(data[at:at+len(raw)])==raw
  stage_relocated={}
  def add_patch(name,at,stored,new):
   decoded=decode_production(stored);encoded=None
   for lazy in (False,True):
    try:
     encoded=reencode_changed_suffix(stored,new,strategy='rust-fit',min_match_length=2,max_match_chain=65536,lazy_matching=lazy,max_output_size=len(stored),original_result=decoded);break
    except ValueError:continue
   if encoded is None:
    encoded=reencode_changed_suffix(stored,new,strategy='rust-fit',min_match_length=2,max_match_chain=65536,lazy_matching=True,original_result=decoded)
    encoded+=bytes((-len(encoded))%16);growth=len(encoded)-slot;assert growth>0
    new_stage=encoded+current_stage[slot:];new_hb=bytearray(hb);table_start=0x5170 if ed=='sp' else 30320;count=69 if ed=='sp' else 206
    values=list(struct.unpack_from('<'+'I'*count,hb,table_start));assert values[0]==0 and values[1]==slot and values[-1]==len(current_stage)
    values=[0]+[v+growth for v in values[1:]];struct.pack_into('<'+'I'*count,new_hb,table_start,*values)
    assert new_stage[len(encoded):]==current_stage[slot:]
    assert hashlib.sha256(decode_production(encoded).output).digest()==hashlib.sha256(new).digest()
    stage_relocated.update({'DATA/STAGE.BIN':new_stage,'HEDBDY/HB.BIN':bytes(new_hb)})
    return
   assert decode_production(encoded).output==new
   patches.append(dict(member=name,offset=at,slot=len(stored),data=encoded.ljust(len(stored),b'\0'),decoded_sha256=hashlib.sha256(new).hexdigest()))
  add_patch('DATA/STAGE.BIN',0,current_stage[:slot],bytes(data))
  name='DATA/MTZSPROS.BIN' if ed=='sp' else 'DATA/MTV_PROS.BIN';archive=member(base,bm,name);native_archive=member(source,sm,name)
  if ed=='sp':
   offsets=[];native_offsets=[]
   for i in range(100):
    offsets.append(struct.unpack_from('<I',current_exe,0x387880+i*4)[0]);native_offsets.append(struct.unpack_from('<I',native_exe,0x387880+i*4)[0])
    if offsets[-1]==len(archive):break
  else:
   spec=CORE_ARCHIVE_SPECS['MTV_PROS.BIN']
   if ed=='best':
    mapping=next(r for r in json.loads((ROOT/'config/editions/best/source-layout.json').read_text())['archive_tables'] if r['member']==name)
    shift=mapping['best_start']-mapping['original_start'];spec=replace(spec,table_start=spec.table_start+shift,table_end=spec.table_end+shift)
   offsets=read_executable_archive_offsets(current_exe,spec,len(archive));native_offsets=read_executable_archive_offsets(native_exe,spec,len(native_archive))
  prose_chunks=[];new_offsets=[0]
  for k,(a,b) in enumerate(zip(offsets,offsets[1:])):
   stored=archive[a:b];decoded=decode_production(stored).output;original_data=decode_production(native_archive[native_offsets[k]:native_offsets[k+1]]).output
   parsed=parse_summary(original_data,table,chunk_index=k)
   # Native metadata owns the fixed allocations; current translated terminators
   # can be shorter and must not redefine a slot's capacity.
   rewritten=bytearray(decoded);grown={}
   for entry in parsed.entries:
    key=f'narration/{k:03d}' if ed=='sp' else entry.entry_id;value=prepared[key];validate_scroll_placeholders(entry.text,value,label=key)
    raw=encode_text(value,table,overrides=codes,terminate=True)
    # Emit the exact encoded C string and recompute the enclosing lengths.
    # Do not carry unused source allocation bytes into the new packet.
    grown[entry.text_offset]=raw
    checks.append(dict(id=key,encoded=len(raw),capacity=entry.allocated_length,decoded_offset=entry.text_offset))
   if grown:
    position=0x3c;sections=[]
    for _ in range(sum(struct.unpack_from('<3I',decoded,0x2c))):
     size=struct.unpack_from('<I',decoded,position+4)[0];end=position+8+size;section=bytes(rewritten[position:end]);at=position+8+0x26
     if at in grown:
      old_length=struct.unpack_from('<I',decoded,at-4)[0];raw=grown[at];payload=section[8:8+0x22]+struct.pack('<I',len(raw))+raw+section[8+0x26+old_length:]
      section=section[:4]+struct.pack('<I',len(payload))+payload
     sections.append(section);position=end
    rebuilt=bytearray(decoded[:0x3c]+b''.join(sections)+decoded[position:]);rebuilt+=bytes((-len(rebuilt))%16)
    struct.pack_into('<I',rebuilt,0x38,sum(map(len,sections)))
    for at in (0xc,0x10):
     assert struct.unpack_from('<I',decoded,at)[0]==len(decoded)-32
     struct.pack_into('<I',rebuilt,at,len(rebuilt)-32)
    rewritten=rebuilt
   reparsed=parse_summary(bytes(rewritten),readback,chunk_index=k)
   assert len(reparsed.entries)==len(parsed.entries)
   for entry in reparsed.entries:
    key=f'narration/{k:03d}' if ed=='sp' else entry.entry_id
    assert entry.text==normalize_original_fullwidth_ascii(prepared[key]),(key,entry.text,prepared[key])
   encoded=reencode_changed_suffix(stored,bytes(rewritten),strategy='rust-fit',min_match_length=2,max_match_chain=16384,lazy_matching=False,original_result=decode_production(stored)) if parsed.entries else stored
   assert decode_production(encoded).output==bytes(rewritten)
   encoded+=bytes((-len(encoded))%16);prose_chunks.append(encoded);new_offsets.append(new_offsets[-1]+len(encoded))
  relocated_archive=b''.join(prose_chunks);patched_exe=bytearray(current_exe)
  table_start=0x387880 if ed=='sp' else spec.table_start
  table_count=len(offsets) if ed=='sp' else len(range(spec.table_start,spec.table_end,4))
  struct.pack_into('<'+'I'*table_count,patched_exe,table_start,*new_offsets[:table_count])
  relocated={name:relocated_archive,cfg['executable']['member']:bytes(patched_exe),**stage_relocated}
  output=args.out/f'{ed}-prose-step-preview.iso'
  if output.exists():
   assert not (args.out/f'{ed}-receipt.json').exists(),'Refuses replacing a completed test build'
   output.unlink()
  subprocess.run(['cp','-c',str(base),str(output)],check=True)
  with output.open('r+b') as f:
   for patch in patches:f.seek(bm[patch['member']].extent_lba*2048+patch['offset']);f.write(patch['data'])
  relocation=append_members(output,bm,relocated,allowed_udf=set(relocated),catalog_policy='inherit')
  verify_relocation(output,bm,relocated,relocation)
  for patch in patches:
   with output.open('rb') as f:f.seek(bm[patch['member']].extent_lba*2048+patch['offset']);actual=f.read(patch['slot'])
   assert actual==patch['data'];assert hashlib.sha256(decode_production(actual).output).hexdigest()==patch['decoded_sha256']
  receipt=dict(edition=ed,base_iso=str(base),base_sha256=manifest['output']['sha256'],output=str(output),sha256=digest(output),source_report_sha256=digest(args.report),native_metric_controls_compiled=True,native_auto_compact_patch_added=False,relocation=relocation,patches=[{k:v for k,v in p.items() if k!='data'} for p in patches],fields=checks,readback_passed=True)
  (args.out/f'{ed}-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');all_receipts.append(receipt);print(ed,len(checks),'fields: test ISO ready',flush=True)
 (args.out/'receipt.json').write_text(json.dumps(all_receipts,indent=2)+'\n')
if __name__=='__main__':main()
