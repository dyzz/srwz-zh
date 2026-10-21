from pathlib import Path
import socket,json,sys
kind=sys.argv[1];first=int(sys.argv[2]);last=int(sys.argv[3]);new=kind=='current';OUT=Path('work/runtime/lrps2')/('automatic-digits-20261021' if new else 'flow-verification-20261021')/'sp';s=socket.socket(socket.AF_UNIX);s.connect('/tmp/srwz-'+('auto-digits' if new else 'flow')+'-sp-20261021.sock');f=s.makefile('rw')
for i in range(first,last+1):
 for c in ('press circle 3','run 120',f'shot story-dialogue-{i:03}'):
  f.write(c+'\n');f.flush();r=[]
  while True:
   l=f.readline().strip();r.append(l)
   if l.startswith(('OK','ERR')):break
   if not l:raise RuntimeError('connection ended')
  if l.startswith('ERR'):raise RuntimeError(r)
  with (OUT/'story-advance.jsonl').open('a') as log:log.write(json.dumps(dict(command=c,response=r))+'\n')
 print(kind,i,flush=True)
f.close();s.close()
