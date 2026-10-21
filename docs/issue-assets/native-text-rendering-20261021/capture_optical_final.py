from pathlib import Path
import concurrent.futures,subprocess,socket,time,json,hashlib
R=Path(__file__).resolve().parents[3]
OUT=R/'work/runtime/lrps2/library-optical-final-20261021'
CARD=Path('/Users/nate/Library/Application Support/ARMSX2/memcards/Mcd001.ps2')
PYTHON=R/'work/runtime/lrps2/python-x86_64-3.12.14/bin/python3'
DRIVER=R/'work/runtime/lrps2/interactive/lrps2_drive.py'
ISOS={'original':'build/iso/zh-release-original/current-original.iso','best':'build/iso/zh-release-best/current-best.iso','sp':'build/iso/special-disc/sp-current.iso'}
sha=lambda p:hashlib.file_digest(p.open('rb'),'sha256').hexdigest()
# Python 3.9 host: explicit streaming hash.
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def capture(ed):
 out=OUT/ed;out.mkdir(parents=True,exist_ok=True);sock=f'/tmp/srwz-optical-final-{ed}-20261021.sock'
 Path(sock).unlink(missing_ok=True)
 log=(out/'driver.log').open('w');p=subprocess.Popen(['arch','-x86_64',str(PYTHON),str(DRIVER),str(R/ISOS[ed]),str(CARD),str(out),sock],stdout=log,stderr=subprocess.STDOUT,cwd=R)
 receipt={'edition':ed,'iso':ISOS[ed],'iso_sha256':sha(R/ISOS[ed]),'source_card_sha256_before':sha(CARD),'commands':[],'controlled_dsc2':ed!='sp'}
 try:
  deadline=time.monotonic()+40
  while not Path(sock).exists():
   if p.poll() is not None:raise RuntimeError(f'{ed} driver exit {p.returncode}')
   if time.monotonic()>deadline:raise TimeoutError(sock)
   time.sleep(.2)
  s=socket.socket(socket.AF_UNIX);s.connect(sock);f=s.makefile('rw')
  def cmd(c):
   f.write(c+'\n');f.flush();lines=[]
   while True:
    line=f.readline().strip();lines.append(line)
    if line.startswith(('OK','ERR')):break
    if not line:raise RuntimeError('connection ended')
   receipt['commands'].append({'command':c,'response':lines})
   if lines[-1].startswith('ERR'):raise RuntimeError(lines)
   return lines
  def press(key,n=3):cmd(f'press {key} {n}')
  cmd('run 1800');press('start');cmd('run 180')
  if ed=='sp':press('right');press('circle');cmd('run 180')
  else:
   for _ in range(3):press('down');cmd('run 55')
   press('circle');cmd('run 240')
  press('down');cmd('run 20');press('circle');cmd('run 180')
  for _ in range(24):press('right')
  press('right')
  for _ in range(4):press('down')
  if ed!='sp':
   press('circle');cmd('run 180');cmd('shot lily-natural-top');press('cross');cmd('run 40')
   flag='58b345' if ed=='original' else '58bb45'
   cmd(f'mem {flag} 1');cmd(f'poke {flag} 81')
  press('circle');cmd('run 180');cmd('shot lily-top');press('down',28);cmd('run 20');cmd('shot lily-scroll');press('cross');cmd('run 40')
  press('right');press('down');press('down');press('circle');cmd('run 180');cmd('shot alex-top');press('down',28);cmd('run 20');cmd('shot alex-scroll');press('cross');cmd('run 40')
  if ed!='sp':cmd(f'poke {flag} 80')
  cmd('shot returned-list')
  press('cross');cmd('run 40');press('up');press('circle');cmd('run 180');cmd('shot robot-list')
  press('circle');cmd('run 180');cmd('shot robot-top');press('down',28);cmd('run 20');cmd('shot robot-scroll')
  state={'original':'46e344','best':'46eb44','sp':'4ed5c4'}[ed];cmd(f'mem {state} 8')
  cmd('quit');p.wait(timeout=15)
  receipt['source_card_sha256_after']=sha(CARD);assert receipt['source_card_sha256_before']==receipt['source_card_sha256_after']
  receipt['status']='captured_pending_visual_review'
 finally:
  if p.poll() is None:p.terminate()
  (out/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n');log.close()
 return ed
if __name__=='__main__':
 with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
  for ed in ex.map(capture,ISOS):print(ed,'captured',flush=True)
