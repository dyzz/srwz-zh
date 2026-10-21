from pathlib import Path
import json,subprocess,socket,time,hashlib,concurrent.futures,struct
R=Path.cwd();OUT=R/'work/runtime/lrps2/native-font-upload-chain-20261021';CARD=Path('/Users/nate/Library/Application Support/ARMSX2/memcards/Mcd001.ps2');DRIVER=R/'work/runtime/lrps2/interactive/lrps2_drive.py';PYTHON=R/'work/runtime/lrps2/python-x86_64-3.12.14/bin/python3'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
core=json.loads((R/'docs/issue-assets/native-text-rendering-20261021/inventory.json').read_text())
submission=json.loads((R/'docs/issue-assets/native-text-rendering-20261021/submission-inventory.json').read_text())
transfer=json.loads((R/'docs/issue-assets/native-text-rendering-20261021/transfer-inventory.json').read_text())
import sys
sys.path.insert(0,str(R/'docs/issue-assets/native-text-rendering-20261021'))
from inventory import native
def capture(ed):
 out=OUT/ed;out.mkdir(parents=True,exist_ok=True);sock=f'/tmp/srwz-native-chain-{ed}-20261021.sock';Path(sock).unlink(missing_ok=True)
 cfg=json.loads((R/f'config/editions/{ed}/edition.json').read_text());iso=R/cfg['source_iso']['path'];log=(out/'driver.log').open('w');before=sha(CARD)
 p=subprocess.Popen(['arch','-x86_64',str(PYTHON),str(DRIVER),str(iso),str(CARD),str(out),sock],stdout=log,stderr=subprocess.STDOUT,cwd=R)
 receipt={'edition':ed,'scope':'native source ISO cold boot, no EE/code/data writes','source_iso':cfg['source_iso'],'native_executable':cfg['executable'],'card_before':before,'commands':[]}
 try:
  deadline=time.monotonic()+45
  while not Path(sock).exists():
   if p.poll() is not None:raise RuntimeError((ed,'driver terminated'))
   if time.monotonic()>deadline:raise TimeoutError(sock)
   time.sleep(.2)
  s=socket.socket(socket.AF_UNIX);s.connect(sock);f=s.makefile('rw')
  def cmd(c,record=True):
   f.write(c+'\n');f.flush();lines=[]
   while True:
    line=f.readline().strip()
    if not line:raise RuntimeError('connection ended')
    lines.append(line)
    if line.startswith(('OK','ERR')):break
   if lines[-1].startswith('ERR'):raise RuntimeError(lines)
   if record:receipt['commands'].append({'command':c,'response':lines})
   return lines
  def memory(addr,size,label):
   lines=cmd(f'mem {addr:x} {size}',False);data=bytes.fromhex(lines[0]);assert len(data)==size
   (out/(label+'.bin')).write_bytes(data)
   receipt['commands'].append({'command':f'mem {addr:x} {size}','output':label+'.bin','sha256':hashlib.sha256(data).hexdigest()})
   return data
  cmd('run 1800');cmd('press start 3');cmd('run 180');cmd('shot native-title')
  info=next(r for r in core['editions'] if r['edition']==ed);F=int(info['state_va'],16)
  state=memory(F,0x90,'font-state');font=struct.unpack_from('<I',state,0x78)[0];atlas=struct.unpack_from('<I',state,0x80)[0]
  assert 0<font<32<<20 and 0<atlas<32<<20,(ed,'font allocation not initialized',hex(font),hex(atlas))
  sr=next(x for x in submission['editions'] if x['edition']==ed);tr=next(x for x in transfer['editions'] if x['edition']==ed);elf,_=native(ed)
  dma_global=int(sr['channel_pointer_global'],16);channel_pointer=struct.unpack('<I',memory(dma_global,4,'channel-pointer'))[0]
  assert channel_pointer==0x1000a000,(ed,'unexpected native channel pointer',hex(channel_pointer))
  origin_global=int(sr['font_chain_origin_global'],16);globals_data=memory(dma_global,0x50,'transfer-globals')
  start=int(tr['blocks'][1]['start'],16)
  def address(hi,lo):
   h,l=elf.words(hi,1)[0],elf.words(lo,1)[0];im=l&65535;return ((h&65535)<<16)+(im-65536 if im&32768 else im)
  chain_base=address(start+0x10,start+0x20);packet_base=address(start+0x18,start+0x28)
  chain_data=memory(chain_base,128,'font-upload-chain');packet_data=memory(packet_base,256,'font-upload-packets')
  tags=[struct.unpack_from('<Q',chain_data,i*16)[0] for i in range(4)]
  expected=[((packet_base&0x0ffffff0)<<32)|0x30000007,((atlas&0xfffffff0)<<32)|0x30000f00,(((packet_base+112)&0x0ffffff0)<<32)|0x30000007,(((atlas+0xf000)&0xfffffff0)<<32)|0x30000f00]
  assert tags==expected,(ed,'two-half font upload tags differ',list(map(hex,tags)),list(map(hex,expected)))
  for i,psm in ((0,0x24),(112,0x2c)):
   assert struct.unpack_from('<Q',packet_data,i+32)[0]==(psm<<56)|(8<<48)|(0x1180<<32)
   assert struct.unpack_from('<Q',packet_data,i+64)[0]==(240<<32)|512
  send=sr['functions']['send_chain'];send_va=int(send['entry'],16);send_size=int(send['end'],16)-send_va;code=memory(send_va,send_size,'native-dma-send-code');assert hashlib.sha256(code).hexdigest()==send['sha256']
  receipt.update(channel_pointer=hex(channel_pointer),font_chain_base=hex(chain_base),font_packet_base=hex(packet_base),chain_tags=list(map(hex,tags)),expected_chain_tags=list(map(hex,expected)),native_dma_code_sha256=hashlib.sha256(code).hexdigest(),inspection_limit='post-frame retained upload buffer snapshot; no within-frame DMA/GS timing trace')
  receipt.update(font_state_hex=state.hex(' '),font_address=hex(font),atlas_address=hex(atlas),reserved_marker=list(struct.unpack_from('<2h',state,12)))
  cmd('quit');p.wait(timeout=15);receipt['card_after']=sha(CARD);assert receipt['card_after']==before
  receipt['status']='native_channel_pointer_and_retained_two_half_upload_chain_verified'
 finally:
  if p.poll() is None:p.terminate()
  (out/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n');log.close()
 return ed
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
 for ed in ex.map(capture,('original','best','sp')):print(ed,'native channel and retained atlas chain verified',flush=True)
