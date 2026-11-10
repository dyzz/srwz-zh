import sys,json,struct,subprocess
from pathlib import Path
sys.path[:0]=['tools','tools/special_disc/writeback']
from srwz.armsx2_runtime import Armsx2Session
from migrate_slps_text import encoding_tables
from srwz.text import encode_text, two_byte_visible_spaces
S=Path(sys.argv[1]);root=Path.cwd()
base=root/'work/runtime/armsx2/battle-punct-overflow-20261109'
out=base/'glyphs';out.mkdir(parents=True,exist_ok=True)
iso=root/'build/iso/zh-release-best/current-best.iso'
card=root/'work/runtime/armsx2/release-skip-20261108/best/save/Mcd001.ps2'
BUF=0x5fe5b8;CAP=96
enc,_,codes,_=encoding_tables()
texts=['“高达Mk-II，出击！目标是Side 3。”','“接招！马赫频带振荡器！\n　GP01，RX-78/2号机！？”','“12.5毫米CIWS，80%！”','“国国国国国国国国国国国国国国国国国国国，”','“Dragon Driver！……Go！”','“什么！？（那是）《高达》【攻击】；是：好、的。”',
 '“'+'国'*19+'！！”','“'+'国'*19+'A”','“'+'国'*18+'Ag9.”']
(S/'g.in.json').write_text(json.dumps(texts,ensure_ascii=False))
subprocess.check_call(['node',str(S/'measure.mjs'),str(S/'g.in.json'),str(S/'g.out.json')])
meas=json.loads((S/'g.out.json').read_text())
rep=[]
with Armsx2Session(iso,card,out) as vm:
    vm.run(5)
    vm.cmd('load '+str(base/'matrix/base.p2s'))
    for pc in ('13ab60','13ab68'):
        vm.cmd('load '+str(base/'matrix/base.p2s'))
        vm.run(1);vm.cmd(f'trace {pc} name=g s0:20');vm.run(1);d=out/'x.jsonl';vm.cmd(f'tracedump {d}');vm.cmd('untrace')
        print(pc,len(d.read_text().splitlines()),d.read_text()[:0])
    for k,(t,m) in enumerate(zip(texts,meas)):
        raw=encode_text(two_byte_visible_spaces(t),enc,overrides=codes,terminate=True);assert len(raw)<=CAP,len(raw)
        vm.cmd('load '+str(base/'matrix/base.p2s'));vm.cmd(f'poke {BUF:x} '+raw.ljust(CAP,b'\0').hex());vm.run(3)
        vm.cmd('trace 13ab50 name=g s0:20');vm.run(1);d=out/'x.jsonl';vm.cmd(f'tracedump {d}');vm.cmd('untrace')
        hs=[json.loads(l) for l in d.read_text().splitlines()]
        # read back the record table after the frame: the draw hook finished, list is still in place
        recs=[]
        for h in hs:
            a=int(h['s0'],16);b=vm.read_ram(a,20);recs.append(struct.unpack('<hhhhHHhh',b[:16]))
        rows={}
        for r in recs:
            if r[3]>=78: rows.setdefault((r[3]-78)//12,[]).append(r)
        for ri in range(len(m)):
            g=[q for q in m[ri]['g'] if q[0] not in ' 　'];got=sorted((r[2]+160,r[6],r[7],r[3]-84-12*ri) for r in rows.get(ri,[]))
            exp=sorted((x,w,h,yo) for _,x,w,h,_,yo in g)
            same=got==exp
            print(k,ri,'match' if same else 'DIFF',len(got),len(exp),'' if same else [(e,gg) for e,gg in zip(exp,got) if e!=gg][:6],flush=True)
            rep.append(dict(text=t,row=ri,match=same,game=got,js=exp))
        vm.shot(f'g{k}')
(out/'glyph-check.json').write_text(json.dumps(rep,ensure_ascii=False))
