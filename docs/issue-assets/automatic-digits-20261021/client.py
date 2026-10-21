from pathlib import Path
import socket,sys,json
R=Path.cwd();ed=sys.argv[1];out=R/'work/runtime/lrps2/automatic-digits-20261021'/ed
s=socket.socket(socket.AF_UNIX);s.connect(f'/tmp/srwz-auto-digits-{ed}-20261021.sock');f=s.makefile('rw')
for c in sys.argv[2:]:
 f.write(c+'\n');f.flush();lines=[]
 while True:
  line=f.readline().strip();lines.append(line)
  if line.startswith(('OK','ERR')):break
  if not line:raise RuntimeError('connection ended')
 with (out/'commands.jsonl').open('a') as log:log.write(json.dumps(dict(command=c,response=lines),ensure_ascii=False)+'\n')
 if lines[-1].startswith('ERR'):raise RuntimeError(lines)
 print(c,lines[:-1] if len(lines)>1 else lines[-1],flush=True)
f.close();s.close()
