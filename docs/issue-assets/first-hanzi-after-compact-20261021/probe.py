"""Controlled RAM text fixture in the real LRPS2 SP flow renderer.
Natural production capture is separate. No code, corpus or ISO writes.
Original pointer and fixture bytes are restored after observation.
"""
from pathlib import Path
import socket,json,struct,hashlib
R=Path.cwd();O=R/'work/runtime/lrps2/first-hanzi-after-compact-20261021/sp';s=socket.socket(socket.AF_UNIX);s.connect('/tmp/srwz-first-hanzi-sp-20261021.sock');f=s.makefile('rw');log=[]
def c(x):
 f.write(x+'\n');f.flush();r=[]
 while True:
  l=f.readline().strip();r.append(l)
  if l.startswith(('OK','ERR')):break
  if not l:raise RuntimeError('connection ended')
 log.append(dict(command=x,response=r))
 if l.startswith('ERR'):raise RuntimeError(r)
 return r
word=bytes.fromhex('93c194a48fac97c4');digits=bytes.fromhex('824f82508252');scope=bytes.fromhex('320e340c')+digits+bytes.fromhex('32103410')
payload=b'\n'.join((word,digits+word,scope+word,word+scope+word))+b'\0';site=0x80baac;at=0x1e00000;pointer=bytes.fromhex(c(f'mem {site:x} 4')[0]);saved=bytes.fromhex(c(f'mem {at:x} {len(payload)}')[0]);assert int.from_bytes(pointer,'little')==0x8093e0
try:
 c(f'poke {at:x} '+payload.hex());c(f'poke {site:x} '+struct.pack('<I',at).hex())
 for x in ('press cross 3','run 30','press circle 3','run 90','shot controlled-same-word'):c(x)
 state=bytes.fromhex(c('mem 4ed5b0 144')[0]);rp=struct.unpack_from('<I',state,0x58)[0];records=bytes.fromhex(c(f'mem {rp:x} 10240')[0]);(O/'controlled-state.bin').write_bytes(state);(O/'controlled-records.bin').write_bytes(records)
 # Four rows: 特别小队; 013特别小队; compact013特别小队;
 # 特别小队compact013特别小队. Expected indices of every 特:
 rows=[]
 for index in (0,7,14,18,25):
  x,y,w,h=struct.unpack_from('<2h',records,index*32+4)+struct.unpack_from('<2h',records,index*32+12);rows.append(dict(record=index,x=x,y=y,width=w,height=h))
 print(rows)
 receipt=dict(scope=__doc__,iso_sha256=json.loads((O/'receipt.json').read_text())['iso_sha256'],fixture_text=['特别小队','013特别小队','<width:0E><space:0C>013<width:10><space:10>特别小队','特别小队<width:0E><space:0C>013<width:10><space:10>特别小队'],fixture_payload_hex=payload.hex(),first_Chinese_records=rows,record_indices=dict(plain=0,after_plain_digits=7,after_compact_digits=14,same_line_before=18,same_line_after=25))
finally:
 c(f'poke {site:x} '+pointer.hex());c(f'poke {at:x} '+saved.hex())
 for x in ('press cross 3','run 30','press circle 3','run 90','shot production-restored'):c(x)
 receipt.update(pointer_restored=bytes.fromhex(c(f'mem {site:x} 4')[0])==pointer,fixture_memory_restored=bytes.fromhex(c(f'mem {at:x} {len(payload)}')[0])==saved,commands=log)
 (O/'controlled-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
f.close();s.close()
