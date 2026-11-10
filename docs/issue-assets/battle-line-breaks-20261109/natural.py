import sys,json,re
from pathlib import Path
sys.path[:0]=['tools','tools/special_disc/writeback']
from srwz.armsx2_runtime import Armsx2Session
from srwz import armsx2_text_probe as P
from migrate_slps_text import encoding_tables
from srwz.text import encode_text, two_byte_visible_spaces
root=Path.cwd();base=root/'work/runtime/armsx2/battle-punct-overflow-20261109'
out=base/'natural';out.mkdir(parents=True,exist_ok=True)
iso=root/'build/iso/test/integrated-best.iso'
card=root/'work/runtime/armsx2/release-skip-20261108/best/save/Mcd001.ps2'
book=P.load_codebook();enc,_,codes,_=encoding_tables()
doc=json.load(open('corpus/zh/battle/srvc-lines.json'))
with Armsx2Session(iso,card,out,renderer='metal',upscale=4) as vm:
    vm.run(5)
    vm.cmd('load '+str(root/'work/runtime/armsx2/release-skip-20261108/best/pre-battle.p2s'))
    for c in P.trace_commands('best'):vm.cmd(c)
    seen=set();first=None
    vm.press('circle',3)
    for n in range(90):
        vm.run(30)
        if n<6 and n%2==1: vm.press('circle',3)
        d=out/'t.jsonl';vm.cmd(f'tracedump {d}')
        for row in P.unique_rows(P.glyph_rows(P.read_hits(d),book)):
            if row.y in(84,96) and (row.y,row.text) not in seen:
                seen.add((row.y,row.text));print(n,row.y,row.x_start,row.x_end,row.text,flush=True)
                if first is None:first=n
                vm.shot(f'row-{len(seen):02d}')
        if first is not None and n>first+40:break
    vm.cmd('untrace')
    vm.cmd(f'dump 0 33554432 {out}/ram.bin')
ram=(out/'ram.bin').read_bytes()
hit=miss=stale=0;ex=[]
old={e['id']:e['translation'] for e in json.loads(__import__('subprocess').check_output(['git','show','HEAD:corpus/zh/battle/srvc-lines.json']))['entries']}
for e in doc['entries']:
    t=e['translation']
    if '<' in t or old[e['id']]==t:continue
    a=encode_text(two_byte_visible_spaces(t.replace('\\n','\n')),enc,overrides=codes,terminate=True).replace(b'\n',b'\\n')
    if ram.find(a)>=0:
        hit+=1;ex.append(t)
    elif old[e['id']]!=t:
        b=encode_text(two_byte_visible_spaces(old[e['id']].replace('\\n','\n')),enc,overrides=codes,terminate=False).replace(b'\n',b'\\n')
        if ram.find(b)>=0:stale+=1
print('two-row lines found in RAM with new break',hit,'old-break found',stale);print(ex[:8])
