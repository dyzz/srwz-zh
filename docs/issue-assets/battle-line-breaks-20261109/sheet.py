import sys,json,struct,subprocess
from pathlib import Path
sys.path[:0]=['tools','tools/special_disc/writeback']
from srwz.armsx2_runtime import Armsx2Session
from migrate_slps_text import encoding_tables
from srwz.text import encode_text, two_byte_visible_spaces
from PIL import Image,ImageDraw,ImageFont
S=Path(sys.argv[1]);root=Path.cwd();base=root/'work/runtime/armsx2/battle-punct-overflow-20261109'
out=base/'sheet';out.mkdir(parents=True,exist_ok=True)
iso=root/'build/iso/test/integrated-best.iso';card=root/'work/runtime/armsx2/release-skip-20261108/best/save/Mcd001.ps2'
BUF=0x5fe5b8;CAP=96;enc,_,codes,_=encoding_tables()
H='这家伙的话不管对手是谁都要打倒给你看到最后'
def r(n,t):return '“'+H[:n]+t
cases=[('real: restored sentence break','“接招！\n　马赫频带振荡器！”'),('real: merged, no longer needs two rows','“你没有领导别人的器量！”'),('real: Latin + digits','“高达Mk-II，出击！\n　目标是Side 3的GP01！”'),
('” adv 452 (budget 462)',r(19,'”')),('” adv 474 (+12)',r(20,'”')),('！” adv 469 (+7)',r(19,'！”')),('！！” adv 486 (+24)',r(19,'！！”')),('！” adv 491 (+29, clipped)',r(20,'！”')),('” adv 496 (+34, clipped)',r(21,'”')),('， row end adv 474 (+12)',r(20,'，')+'\n　后面”')]
meas_in=[c[1] for c in cases];(S/'sh.in.json').write_text(json.dumps(meas_in,ensure_ascii=False))
subprocess.check_call(['node',str(S/'measure.mjs'),str(S/'sh.in.json'),str(S/'sh.out.json')]);M=json.loads((S/'sh.out.json').read_text())
rep=[];strips=[]
with Armsx2Session(iso,card,out,renderer='metal',upscale=4) as vm:
    vm.run(5)
    for k,((lab,t),m) in enumerate(zip(cases,M)):
        raw=encode_text(two_byte_visible_spaces(t),enc,overrides=codes,terminate=True);assert len(raw)<=CAP
        vm.cmd('load '+str(base/'matrix/base.p2s'));vm.cmd(f'poke {BUF:x} '+raw.ljust(CAP,b'\0').hex());vm.run(3)
        vm.cmd('trace 13ab50 name=g s0:20');vm.run(1);d=out/'x.jsonl';vm.cmd(f'tracedump {d}');vm.cmd('untrace')
        recs=[struct.unpack('<hhhhHHhh',vm.read_ram(int(json.loads(l)['s0'],16),20)[:16]) for l in d.read_text().splitlines()]
        rows={}
        for q in recs:
            if q[3]>=78:rows.setdefault((q[3]-78)//12,[]).append(q)
        ok=True
        for ri,row in enumerate(m):
            got=sorted((q[2]+160,q[6],q[7],q[3]-84-12*ri) for q in rows.get(ri,[]));exp=sorted((x,w,h,yo) for _,x,w,h,_,yo in row['g'])
            ok&=got==exp
        vm.shot(f's{k}');rep.append(dict(label=lab,text=t,glyphs_match=ok,rows=[(x['adv'],x['occ']) for x in m]));print(k,lab,ok,flush=True)
        im=Image.open(out/f's{k}.png').convert('RGB');W,Hh=im.size;strips.append((lab,ok,im.crop((W//4-40,int(Hh*.84),W,Hh))))
f=ImageFont.truetype('/System/Library/Fonts/Hiragino Sans GB.ttc',36)
w=strips[0][2].size[0];h=strips[0][2].size[1]+56
sheet=Image.new('RGB',(w,h*len(strips)),(18,18,22));dr=ImageDraw.Draw(sheet)
for i,(lab,ok,c) in enumerate(strips):
    dr.text((12,i*h+4),f'{lab}   glyph geometry: {"match" if ok else "DIFF"}',fill=(235,235,235),font=f);sheet.paste(c,(0,i*h+56))
sheet=sheet.resize((w//2,sheet.size[1]//2));sheet.save(base/'overflow-sheet.png');(base/'sheet.json').write_text(json.dumps(rep,ensure_ascii=False,indent=1))
print(sheet.size)
