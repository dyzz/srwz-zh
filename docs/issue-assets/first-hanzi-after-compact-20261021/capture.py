"""Natural LRPS2 flow-page navigation with rebuilt production ISOs; read-only EE."""
from pathlib import Path
import concurrent.futures,subprocess,socket,time,json,hashlib
R=Path.cwd();OLD=R/'work/runtime/lrps2/flow-verification-20261021';OUT=R/'work/runtime/lrps2/first-hanzi-after-compact-20261021';CARD=Path('/Users/nate/Library/Application Support/ARMSX2/memcards/Mcd001.ps2');PY=R/'work/runtime/lrps2/python-x86_64-3.12.14/bin/python3';DRIVER=R/'work/runtime/lrps2/interactive/lrps2_drive.py'
ISOS={'original':'build/iso/zh-release-original/current-original.iso','best':'build/iso/zh-release-best/current-best.iso','sp':'build/iso/special-disc/sp-current.iso'}
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def capture(ed):
 out=OUT/ed;out.mkdir(parents=True,exist_ok=True);sock=f'/tmp/srwz-first-hanzi-{ed}-20261021.sock';log=(out/'driver.log').open('w');iso=R/ISOS[ed]
 receipt=dict(edition=ed,scope=__doc__,iso=ISOS[ed],iso_sha256=sha(iso),source_card_sha256_before=sha(CARD),commands=[])
 p=subprocess.Popen(['arch','-x86_64',str(PY),str(DRIVER),str(iso),str(CARD),str(out),sock],stdout=log,stderr=subprocess.STDOUT,cwd=R)
 try:
  until=time.monotonic()+45
  while not Path(sock).exists():
   if p.poll() is not None:raise RuntimeError((ed,p.returncode))
   if time.monotonic()>until:raise TimeoutError(sock)
   time.sleep(.2)
  s=socket.socket(socket.AF_UNIX);s.connect(sock);f=s.makefile('rw')
  def cmd(c):
   f.write(c+'\n');f.flush();r=[]
   while True:
    l=f.readline().strip();r.append(l)
    if l.startswith(('OK','ERR')):break
    if not l:raise RuntimeError('connection ended')
   receipt['commands'].append(dict(command=c,response=r))
   if l.startswith('ERR'):raise RuntimeError(r)
   return r
  for row in json.loads((R/'docs/issue-assets/automatic-digits-20261021/flow'/ed/'receipt.json').read_text())['commands']:
   c=row['command']
   if c.split()[0] in ('run','press','shot'):cmd(c)
   if c=='shot target-reopened':break
  F={'original':0x46e330,'best':0x46eb30,'sp':0x4ed5b0}[ed];state=bytes.fromhex(cmd(f'mem {F:x} 144')[0]);(out/'font-state.bin').write_bytes(state)
  import struct
  pointer=struct.unpack_from('<I',state,0x58)[0];records=bytes.fromhex(cmd(f'mem {pointer:x} 10240')[0]);(out/'glyph-records.bin').write_bytes(records)
  receipt.update(source_card_sha256_after=sha(CARD),status='natural_capture_pending_visual_review');assert receipt['source_card_sha256_before']==receipt['source_card_sha256_after']
  # Keep this process live for follow-up story navigation and read-only ISO/RAM proof.
  (out/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n');f.close();s.close()
  print(ed,'natural flow captured; live driver',p.pid,sock,flush=True)
 finally:log.close()
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(capture,('sp',)))
