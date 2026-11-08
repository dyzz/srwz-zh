import sys,json,struct,socket,zipfile,hashlib
from pathlib import Path
sys.path.insert(0,'tools')
from srwz.armsx2_runtime import Armsx2Session
from srwz.tag_free_integrated import build_payload
root=Path.cwd();registry=json.loads((root/'shared/text-layout/proportional-metrics.mjs').read_text().split(' = ',1)[1].rstrip(';\n'))
for e,state in [('best',0x46eb30),('sp',0x4ed5b0)]:
 out=root/f'work/runtime/armsx2/keyword-list-20261108/{e}';ram=zipfile.ZipFile(out/'list-page2.p2s').read('eeMemory.bin')
 v=Armsx2Session(root/'unused',root/'unused',out);v._socket=socket.socket(socket.AF_UNIX);v._socket.connect(f'/tmp/keyword-list-{e}.sock');v._stream=v._socket.makefile('rw')
 font=struct.unpack_from('<I',ram,state+0x78)[0];assert 0<font<0x2000000-1290240
 assert v.read_ram(font,1290240)==ram[font:font+1290240]
 payload,patches,report=build_payload(registry,e,scene_dispatch=True)
 v.cmd('load list-page2')
 for address,length in [(report['base'],len(payload))]+[(a,len(b))for a,b,c in patches]+[(0x1e00000,0x4000)]:
  assert v.read_ram(address,length)==ram[address:address+length]
 (out/'restoration.json').write_text(json.dumps(dict(fontUnchanged=True,fontSha256=hashlib.sha256(ram[font:font+1290240]).hexdigest(),hooksAndPayloadRestored=True,measureScratchRestored=True,productionIsoWritten=False),indent=2)+'\n')
 v.cmd('quit');print(e,'font unchanged; baseline code and scratch restored; runner stopped')
