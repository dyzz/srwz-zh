"""All decoded native/current STAGE raw opcode5039 candidates and source text.
The native dispatch establishes opcode semantics. Opcode+pointer shape scanning
alone is not a rooted script/reachability proof. Every raw hit is retained and
classified, including invalid/unmatched ones, rather than silently filtered.
"""
from pathlib import Path
import json,sys,struct,hashlib,collections
OUT=Path(__file__).parent;ROOT=OUT.parents[2];sys.path[:0]=[str(ROOT/'tools'),str(OUT)]
from srwz.iso9660 import member_map,scan_iso9660
from srwz.codec import decode_production
from srwz.text import load_text_table,decode_text,project_runtime_text_table,original_fullwidth_ascii_overrides
from special_disc.writeback.migrate_library import sp_offsets
T=load_text_table(ROOT/'vendor/upstream-python/project/tbl_all.json');batch=json.loads((OUT/'optical-production-build.json').read_text());results=[]
frozen_project=(ROOT/batch['results'][0]['readback']['path']).parents[1]
codebook_paths=[frozen_project/'config/encoding/codebook.json',frozen_project/'work/writeback/zh-release-codebook-proposal.json']
book,proposal=[json.loads(p.read_text()) for p in codebook_paths]
overrides={x['character']:int(x['code'],16) for x in book['assignments']+proposal['assignments']}
overrides.update({x['character']:int(x['code'],16) for x in proposal.get('surface_alias_assignments',[])})
overrides.update(original_fullwidth_ascii_overrides(T));ZH=project_runtime_text_table(T,overrides)
for ed in ('original','best','sp'):
 cfg=json.loads((ROOT/f'config/editions/{ed}/edition.json').read_text());base=int(cfg['layout']['stage_base'],16);versions=[]
 for version,path in [('native',cfg['source_iso']['path']),('current',next(x for x in batch['results'] if x['edition_id']==ed)['output']['path'])]:
  iso=ROOT/path;m=member_map(scan_iso9660(iso))
  def read(name):
   x=m[name]
   with iso.open('rb') as f:f.seek(x.extent_lba*2048);return f.read(x.size)
  data=read('DATA/STAGE.BIN');hb=read('HEDBDY/HB.BIN');offsets=sp_offsets(hb,0x5170 if ed=='sp' else 30320,len(data));hits=[]
  for index,(left,right) in enumerate(zip(offsets,offsets[1:])):
   decoded=decode_production(data[left:right]).output;at=decoded.find(struct.pack('<I',5039))
   while at>=0:
    row=dict(chunk=index,offset=at,aligned=at%4==0,raw_record_hex=decoded[at:at+12].hex(' '),decoded_chunk_sha256=hashlib.sha256(decoded).hexdigest(),context_hex=decoded[max(0,at-16):at+28].hex(' '),classification='unclassified raw opcode bytes')
    if at+12<=len(decoded):
     arg,pointer=struct.unpack_from('<2I',decoded,at+4);target=pointer-base;row.update(argument=hex(arg),selector=arg>>16,value=arg&65535,text_pointer=hex(pointer),text_offset=target)
     if 0<=target<len(decoded):
      end=decoded.find(b'\0',target)
      if end>=target:
       raw=decoded[target:end];text=decode_text(raw+b'\0',0,T if version=='native' else ZH);controls=[];pos=0
       while pos<len(raw):
        b=raw[pos]
        if 0x30<=b<=0x3d:
         controls.append(dict(offset=pos,opcode=hex(b),operand=raw[pos+1] if b<=0x39 and pos+1<len(raw) else None));pos+=2 if b<=0x39 else 1
        elif b in (0x0a,0x2e,0x2f):controls.append(dict(offset=pos,opcode=hex(b),operand=None));pos+=1
        else:pos+=2 if b>=0x80 else 1
       row.update(classification='aligned opcode and internal NUL text pointer candidate' if at%4==0 else 'unaligned opcode and internal text pointer candidate',text=text.text,unknown_codes=text.unknown_code_count,text_bytes=len(raw),text_sha256=hashlib.sha256(raw).hexdigest(),raw_text_hex=raw.hex(' '),controls=controls,height_controls=[x for x in controls if x['opcode']=='0x33'])
    hits.append(row);at=decoded.find(struct.pack('<I',5039),at+1)
  versions.append(dict(version=version,iso=str(path),stage_member_sha256=hashlib.sha256(data).hexdigest(),hb_member_sha256=hashlib.sha256(hb).hexdigest(),chunks=len(offsets)-1,hit_count=len(hits),classifications=dict(collections.Counter(x['classification'] for x in hits)),hits=hits));print(ed,version,len(hits),'raw opcode hits',dict(collections.Counter(x['classification'] for x in hits)),flush=True)
 results.append(dict(edition=ed,versions=versions))
(OUT/'name-command-source-audit.json').write_text(json.dumps(dict(scope=__doc__,status='all_raw_opcode_hits_classified_not_rooted_reachability',production_batch=batch['input_digest'],decoding_codebooks=[dict(path=str(p.relative_to(ROOT)),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in codebook_paths],editions=results),ensure_ascii=False,indent=2)+'\n')
