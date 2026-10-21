from pathlib import Path
import sys,json,struct,hashlib,subprocess,concurrent.futures
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'tools'))
from srwz.iso9660 import member_map,scan_iso9660
from srwz.codec import decode_production
B=R/'docs/issue-assets/automatic-digits-20261021/production-build.json';batch=json.loads(B.read_text());OUT=R/'work/runtime/lrps2/automatic-digits-20261021'
sha=lambda b:hashlib.sha256(b).hexdigest()
def filehash(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def cmd(ed,c):
 subprocess.run([sys.executable,str(Path(__file__).parent/'client.py'),ed,c],cwd=R,check=True,stdout=subprocess.DEVNULL)
 return json.loads((OUT/ed/'commands.jsonl').read_text().splitlines()[-1])['response'][0]
rows=[]
for ed,base,site,target in [('original',0x7566f0,0x10e0c,'overview:014'),('best',0x756ef0,0x10e0c,'overview:014'),('sp',0x8045f0,0x74bc,'synopsis/002')]:
 result=next(x for x in batch['results'] if x['edition_id']==ed);iso=R/result['output']['path'];m=member_map(scan_iso9660(iso))['DATA/STAGE.BIN']
 with iso.open('rb') as f:f.seek(m.extent_lba*2048);decoded=decode_production(f.read(min(m.size,1<<18))).output
 pointer=struct.unpack_from('<I',decoded,site)[0];at=pointer-base;assert 0<=at<len(decoded)
 n=decoded.index(0,at)+1;expected=decoded[at:n]
 livepointer=bytes.fromhex(cmd(ed,f'mem {base+site:x} 4'));assert struct.unpack('<I',livepointer)[0]==pointer
 live=bytes.fromhex(cmd(ed,f'mem {pointer:x} {len(expected)}'));assert live==expected,(ed,'loaded text differs from ISO')
 iso_hash=filehash(iso);assert iso_hash==result['output']['sha256']
 row=dict(edition=ed,target=target,iso=result['output'],loaded_pointer=f'0x{pointer:X}',pointer_site=f'0x{base+site:X}',payload_size=len(expected),payload_sha256=sha(expected),loaded_payload_matches_current_iso=True,iso_sha256_rechecked=True)
 rows.append(row);print(ed,target,'loaded text matches ISO',len(expected),'bytes',flush=True)
(OUT/'loaded-text-proof.json').write_text(json.dumps(dict(batch=batch['input_digest'],cases=rows),indent=2)+'\n')
