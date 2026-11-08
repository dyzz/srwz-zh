import sys,json,socket,struct,subprocess
from pathlib import Path
sys.path.insert(0,'tools')
from srwz.armsx2_runtime import Armsx2Session
from srwz.proportional_hooks import Asm
from srwz.tag_free_integrated import build_payload
from srwz.armsx2_text_probe import load_codebook
root=Path.cwd();e=sys.argv[1];out=root/f'work/runtime/armsx2/keyword-list-20261108/{e}'
v=Armsx2Session(root/'unused',root/'unused',out);v._socket=socket.socket(socket.AF_UNIX);v._socket.connect(f'/tmp/keyword-list-{e}.sock');v._stream=v._socket.makefile('rw')
r=json.loads((root/'shared/text-layout/proportional-metrics.mjs').read_text().split(' = ',1)[1].rstrip(';\n'))
texts=['Side　3','Evidence　01','LOGOS','PLANT评议会议长'];enc={v:k for k,v in load_codebook().items()}
def encode(s):
 b=bytearray()
 for ch in s:
  if ch=='　':code=0x8140
  elif ch in r['profiles']['keyword_list']['glyphs']:code=r['profiles']['keyword_list']['glyphs'][ch]['code']
  else:code=enc[ch]
  b.extend(code.to_bytes(2,'big'))
 return bytes(b)+b'\0'
site=0x13ab58 if e=='best' else 0x13b5f8;measure=0x139b00 if e=='best' else 0x13a5a0
cave=0x1e00000;result=cave+0x3000;textbase=cave+0x3100
results={}
for variant in ['baseline','candidate']:
 v.cmd('load list-page1')
 old=v.read_ram(cave,0x4000);assert old==bytes(len(old)), 'scratch occupied'
 if variant=='candidate':
  payload,patches,report=build_payload(r,e,scene_dispatch=True)
  for addr,data in [(report['base'],payload)]+[(a,c)for a,b,c in patches]:
   for i in range(0,len(data),256):v.cmd(f'poke {addr+i:x} {data[i:i+256].hex()}')
 original_site=v.read_ram(site,8)
 a=Asm();a.i(9,'sp','sp',-512)
 regs='at v0 v1 a0 a1 a2 a3 t0 t1 t2 t3 t4 t5 t6 t7 s0 s1 s2 s3 s4 s5 s6 s7 t8 t9 k0 k1 gp fp ra'.split()
 for i,reg in enumerate(regs):a.i(0x1f,'sp',reg,i*16)
 a.li('t0',result);a.i(0x23,'t0','t1',0);a.branch(5,'t1','zero','restore')
 for i,s in enumerate(texts):
  # Native measurement consumes width/advance; height is drawing-only.
  raw=bytes.fromhex('32123412')+encode(s);v.cmd(f'poke {textbase+i*128:x} {raw.hex()}')
  for flag in [1,0]:
   a.li('a0',textbase+i*128);a.li('a1',flag);a.emit(0x0c000000|(measure>>2));a.emit(0)
   a.li('t0',result);a.i(0x2b,'t0','v0',4+(i*2+(1-flag))*4)
 a.i(9,'zero','t1',1);a.i(0x2b,'t0','t1',0)
 a.label('restore')
 for i,reg in enumerate(regs):a.i(0x1e,'sp',reg,i*16)
 a.i(9,'sp','sp',512)
 for word in struct.unpack('<II',original_site):a.emit(word)
 code=a.finish()
 for i in range(0,len(code),256):v.cmd(f'poke {cave+i:x} {code[i:i+256].hex()}')
 v.cmd(f'poke {site:x} '+struct.pack('<II',0x08000000|(cave>>2),0).hex())
 v.run(2);values=struct.unpack('<9i',v.read_ram(result,36));assert values[0]==1,values
 results[variant]=values[1:];print(variant,values,flush=True)
v.cmd('load list-page1');assert v.read_ram(cave,0x4000)==bytes(0x4000)
js="import {measure} from './shared/text-layout/proportional.mjs'; console.log(JSON.stringify(JSON.parse(process.argv[1]).map(t=>measure(t,'keyword_list').rows[0].advancePx)))"
widths=json.loads(subprocess.check_output(['/opt/homebrew/bin/node','--input-type=module','-e',js,json.dumps(texts)],text=True))
expected=[v for w in widths for v in [w,-(w//2)]]
assert list(results['candidate'])==expected,(results,expected)
(out/'measure-verification.json').write_text(json.dumps(dict(evidence='ARMSX2 native measure component call, not natural list centering',texts=texts,results=results,expected=expected,scratch_restored=True),indent=2,ensure_ascii=False)+'\n')
