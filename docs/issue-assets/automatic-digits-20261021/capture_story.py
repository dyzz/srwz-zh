"""Replay only natural input on the new SP production ISO, starting at flow detail.
Previous RAM experiments are excluded. No state-load or EE writes occur.
"""
from pathlib import Path
import socket,json
R=Path.cwd();OUT=R/'work/runtime/lrps2/automatic-digits-20261021/sp';old=R/'work/runtime/lrps2/flow-verification-20261021/sp/commands.jsonl';s=socket.socket(socket.AF_UNIX);s.connect('/tmp/srwz-auto-digits-sp-20261021.sock');f=s.makefile('rw');receipt=dict(scope=__doc__,commands=[]);started=False
for l in old.read_text().splitlines():
 c=json.loads(l)['command']
 if c=='shot digits-restored-source':started=True;continue
 if not started or c.split()[0] not in ('run','press','shot'):continue
 f.write(c+'\n');f.flush();r=[]
 while True:
  x=f.readline().strip();r.append(x)
  if x.startswith(('OK','ERR')):break
  if not x:raise RuntimeError('connection ended')
 if x.startswith('ERR'):raise RuntimeError(r)
 receipt['commands'].append(dict(command=c,response=r))
 if c.startswith('shot '):print(c,flush=True)
 if c=='shot story-dialogue-002':break
(OUT/'story-replay-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n');f.close();s.close()
