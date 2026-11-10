import sys,json,struct,subprocess
from pathlib import Path
sys.path[:0]=['tools','tools/special_disc/writeback']
from srwz.armsx2_runtime import Armsx2Session
from migrate_slps_text import encoding_tables
from srwz.text import encode_text, two_byte_visible_spaces
import numpy as np
from PIL import Image
S=Path(sys.argv[1]);root=Path.cwd()
out=root/'work/runtime/armsx2/battle-punct-overflow-20261109/matrix';out.mkdir(parents=True,exist_ok=True)
iso=root/'build/iso/zh-release-best/current-best.iso'
card=root/'work/runtime/armsx2/release-skip-20261108/best/save/Mcd001.ps2'
BUF=0x5fe5b8;CAP=96
enc,_,codes,_=encoding_tables()
tails=['”','！”','？”','！！”','！？”','…”','……”','—”','。”','，','。','、','！','？','：','；','）','》','】','A','g','W','i','0','1','-','.','/','%','国']
cases=[]
for t in tails:
    cases.append(dict(id=f'ref|{t}',text='“国国国国国'+t,ref=True))
    for n in range(17,24):
        cases.append(dict(id=f'{n}|{t}',text='“'+'国'*n+t))
texts=[c['text'] for c in cases]
(S/'mx.in.json').write_text(json.dumps(texts,ensure_ascii=False))
subprocess.check_call(['node',str(S/'measure.mjs'),str(S/'mx.in.json'),str(S/'mx.out.json')])
meas=json.loads((S/'mx.out.json').read_text())
def rec(h):return struct.unpack('<hhhhHHhh',bytes.fromhex(h['mem']['s0:20'])[:16])
res=[];bad=[]
with Armsx2Session(iso,card,out) as vm:
    vm.run(5)
    vm.cmd('load '+str(root/'work/runtime/armsx2/release-skip-20261108/best/animation-start.p2s'))
    vm.run(60);vm.cmd('state base')
    def play(raw,name):
        vm.cmd('load base');vm.cmd(f'poke {BUF:x} '+raw.ljust(CAP,b'\0').hex())
        vm.run(3);vm.cmd('trace 13ab50 name=glyph @70000060:2 s0:20');vm.run(1)
        d=out/'t.jsonl';vm.cmd(f'tracedump {d}');vm.cmd('untrace');vm.shot(name)
        hs=[json.loads(l) for l in d.read_text().splitlines()]
        return hs
    play(b'\0','base-empty')
    B=np.asarray(Image.open(out/'base-empty.png').convert('RGB')).astype(int)
    for c,m in zip(cases,meas):
        raw=encode_text(two_byte_visible_spaces(c['text']),enc,overrides=codes,terminate=True)
        assert len(raw)<=CAP,(c['id'],len(raw))
        name=f"c{len(res):03d}"
        hs=play(raw,name)
        rs=[rec(h) for h in hs];rs=[r for r in rs if r[3]==84]
        A=np.asarray(Image.open(out/(name+'.png')).convert('RGB')).astype(int)
        D=np.abs(A-B).sum(axis=2)[388:420,:]>24
        cols=np.where(D.any(axis=0))[0]
        right=int(cols.max()) if len(cols) else None
        g=m[0]['g']
        ok=len(rs)==len(g) and all(r[2]+160==x and r[6]==w for r,(_,x,w,*_) in zip(rs,g))
        if not ok: bad.append(c['id'])
        res.append(dict(id=c['id'],text=c['text'],adv=m[0]['adv'],occ=m[0]['occ'],last_x=g[-1][1],last_w=g[-1][2],last_adv=g[-1][4],prev_x=g[-2][1],game_n=len(rs),game_last=(rs[-1][2]+160,rs[-1][6]) if rs else None,match=ok,screen_right=right))
        if not len(res)%25:print(len(res),flush=True)
(out/'matrix.json').write_text(json.dumps(res,ensure_ascii=False,indent=0))
print('cases',len(res),'mismatch',len(bad),bad[:20])
