import sys,json,struct,subprocess
from pathlib import Path
sys.path[:0]=['tools','tools/special_disc/writeback']
from srwz.armsx2_runtime import Armsx2Session
from srwz import armsx2_text_probe as P
from migrate_slps_text import encoding_tables
from srwz.text import encode_text, two_byte_visible_spaces
root=Path.cwd();base=root/'work/runtime/armsx2/battle-punct-overflow-20261109'
out=base/'timing';out.mkdir(parents=True,exist_ok=True)
iso=root/'build/iso/test/integrated-best.iso';card=root/'work/runtime/armsx2/release-skip-20261108/best/save/Mcd001.ps2'
enc,_,codes,_=encoding_tables();e=lambda t:encode_text(t,enc,overrides=codes,terminate=False)
one=e('“是超限冻结弹！”');two=e('“是超限')+b'\\n'+e('　')+e('弹！”');assert len(one)==len(two)
res={}
def go(vm,label,patch):
    vm.cmd('load '+str(root/'work/runtime/armsx2/release-skip-20261108/best/animation-start.p2s'))
    ram=vm.read_ram(0x1600000,0x200000)
    if patch:
        i=-1;n=0
        while True:
            i=ram.find(one,i+1)
            if i<0:break
            vm.cmd(f'poke {0x1600000+i:x} '+two.hex());n+=1
        print('patched',n)
    vm.cmd('trace 13ab50 name=g s0:20')
    f=set();y96=set();start=vm.frame
    for _ in range(38):
        vm.run(20);d=out/'t.jsonl';vm.cmd(f'tracedump {d}')
        for l in d.read_text().splitlines():
            h=json.loads(l);q=struct.unpack('<hhhhHHhh',bytes.fromhex(h['mem']['s0:20'])[:16])
            if q[3]==84:f.add(h['frame']-start)
            if q[3]==96:y96.add(h['frame']-start)
    vm.cmd('untrace')
    fs=sorted(x for x in f);gaps=[];s=fs[0];p=fs[0]
    for x in fs[1:]:
        if x>p+2:gaps.append((s,p));s=x
        p=x
    gaps.append((s,p));res[label]=dict(spans=gaps,row2=(min(y96),max(y96)) if y96 else None);print(label,res[label],flush=True)
with Armsx2Session(iso,card,out) as vm:
    vm.run(5);go(vm,'one-row',False);go(vm,'two-row',True)
(out/'timing.json').write_text(json.dumps(res))
