from pathlib import Path
import sys,struct,json,hashlib,re
W=Path(__file__).resolve().parent;R=W.parents[2];sys.path.insert(0,str(R/'tools'))
from srwz.iso9660 import scan_iso9660,member_map
p=R/'build/iso/zh-release-original/current-original.iso';im=scan_iso9660(p);ms=sorted(im.members,key=lambda m:m.extent_lba);rows=[];matches=[]
with p.open('rb') as f:
 for m in ms:
  if m.size<10000000 or 'MODULE' in m.path or 'IOPRP' in m.path or 'DMY' in m.path:
   f.seek(m.extent_lba*2048);b=f.read(m.size)
   hits=[dict(offset=hex(v.start()),context=repr(b[max(0,v.start()-24):v.end()+64])) for v in re.finditer(rb'(?i)dmy|dummy',b)]
   if hits:matches.append(dict(member=m.path,hits=hits[:100],count=len(hits)))
   if m.path.startswith('SLPS'):(W/m.path).write_bytes(b)
 for a,b in zip(ms,ms[1:]):
  start=(a.extent_lba+(a.size+2047)//2048)*2048;end=b.extent_lba*2048
  if end>start:
   f.seek(start);v=f.read(end-start)
   rows.append(dict(after=a.path,before=b.path,start_lba=start//2048,end_lba=end//2048,bytes=end-start,nonzero=len(v)-v.count(0)))
 m=ms[-1];start=(m.extent_lba+(m.size+2047)//2048)*2048;f.seek(start);v=f.read();rows.append(dict(after=m.path,before='ISO_END',start_lba=start//2048,end_lba=p.stat().st_size//2048,bytes=len(v),nonzero=len(v)-v.count(0)))
result=dict(iso=str(p),size=p.stat().st_size,filename_hits=matches,gaps=rows)
(W/'static-audit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
