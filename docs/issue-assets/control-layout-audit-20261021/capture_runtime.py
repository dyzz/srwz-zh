from pathlib import Path
import sys,json,re,time,socket,subprocess,concurrent.futures,hashlib
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'work/analysis/library-font-fix-20261021'))
import capture_height as c
OUT=R/'work/runtime/lrps2/control-layout-audit-20261021'
legacy=R/'work/runtime/lrps2/post-v042-20261006/after/commands.jsonl'
cmds=[r['command'] for r in map(json.loads,legacy.read_text().splitlines()) if 'command'in r]
commands=[v for v in cmds[:99] if v.startswith(('run ','press ')) or v in ('shot viewer','shot gravion-weapon-list','shot button-before')]
commands+=['press triangle 3','run 90','shot triangle-action','press cross 3','run 90','shot returned-weapon-list','quit']

def buttons():
 out=OUT/'sp-controls';out.mkdir(parents=True,exist_ok=True);sock='/tmp/srwz-control-audit-sp-20261021.sock';Path(sock).unlink(missing_ok=True)
 log=(out/'driver.log').open('w');iso=R/c.ISOS['sp']
 receipt=dict(iso=c.ISOS['sp'],iso_sha256=c.sha(iso),source_card_sha256_before=c.sha(c.CARD),commands=[],mode='LRPS2 cold boot and natural button navigation; no RAM patches or save-state restore',navigation_source=str(legacy.relative_to(R)),navigation_source_sha256=c.sha(legacy))
 proc=subprocess.Popen(['arch','-x86_64',str(c.PYTHON),str(c.DRIVER),str(iso),str(c.CARD),str(out),sock],stdout=log,stderr=subprocess.STDOUT,cwd=R)
 try:
  deadline=time.monotonic()+40
  while not Path(sock).exists():
   if proc.poll()is not None:raise RuntimeError(proc.returncode)
   if time.monotonic()>deadline:raise TimeoutError(sock)
   time.sleep(.2)
  s=socket.socket(socket.AF_UNIX);s.connect(sock);f=s.makefile('rw')
  for command in commands:
   f.write(command+'\n');f.flush();lines=[]
   while True:
    line=f.readline().strip();lines.append(line)
    if line.startswith(('OK','ERR')):break
    if not line:raise RuntimeError('connection ended')
   receipt['commands'].append(dict(command=command,response=lines))
   if lines[-1].startswith('ERR'):raise RuntimeError(lines)
  proc.wait(timeout=15)
  receipt['source_card_sha256_after']=c.sha(c.CARD);assert receipt['source_card_sha256_before']==receipt['source_card_sha256_after'];receipt['status']='captured_pending_visual_review'
 finally:
  if proc.poll()is None:proc.terminate()
  log.close();(out/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
 print('sp-controls captured',flush=True)

if __name__=='__main__':
 log=R/'work/analysis/control-layout-audit-20261021/build-final.log';deadline=time.monotonic()+300
 while True:
  match=re.search(r'"batch_manifest": "([^"]+)"',log.read_text() if log.exists() else '')
  if match:break
  if time.monotonic()>deadline:raise TimeoutError('final build incomplete')
  time.sleep(2)
 c.OUT=OUT/'characters'
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
  jobs=[pool.submit(c.capture,ed) for ed in c.ISOS]+[pool.submit(buttons)]
  for j in concurrent.futures.as_completed(jobs):print('completed',j.result(),flush=True)
