import sys,json,socket
from pathlib import Path
sys.path.insert(0,'tools')
from srwz.tag_free_integrated import build_payload
from srwz.armsx2_runtime import Armsx2Session
root=Path(__file__).resolve().parents[3];e=sys.argv[1];out=root/f'work/runtime/armsx2/keyword-list-20261108/{e}'
r=json.loads((root/'shared/text-layout/proportional-metrics.mjs').read_text().split(' = ',1)[1].rstrip(';\n'))
payload,patches,report=build_payload(r,e,scene_dispatch=True)
v=Armsx2Session(root/'unused',root/'unused',out);v._socket=socket.socket(socket.AF_UNIX);v._socket.connect(f'/tmp/keyword-list-{e}.sock');v._stream=v._socket.makefile('rw')
for addr,data in [(report['base'],payload)]+[(a,c)for a,b,c in patches]:
 for i in range(0,len(data),256):v.cmd(f'poke {addr+i:x} {data[i:i+256].hex()}')
 assert v.read_ram(addr,len(data))==data
(out/'candidate-payload.json').write_text(json.dumps(report,indent=2)+'\n')
page=sys.argv[2] if len(sys.argv)>2 else 'page1'
v.run(4);v.shot('after-'+page)
v.cmd('trace '+('13ab60' if e=='best' else '13b600')+' name=draw s0:32 s4:32 @70000060:2')
v.run(2);v.cmd('tracedump '+str(out/('list-after-'+page+'.jsonl')));v.cmd('untrace')
print(report['codeBytes'],flush=True)
