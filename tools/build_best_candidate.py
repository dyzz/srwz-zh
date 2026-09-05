#!/usr/bin/env python3
"""Experimental Best-edition port, isolated from the Original production build.

Consumes hash-locked Original Chinese components as a temporary migration
snapshot. The production source-based Best pipeline is a later milestone.
All generated files remain under work/build/best-alpha1 and build/iso/best-alpha1.
"""
from __future__ import annotations
import argparse
import bisect
import collections
import difflib
import hashlib
import functools
import json
import shutil
import struct
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'work/build/best-alpha1'
ANALYSIS=ROOT/'work/analysis/original-vs-best-20260905'
BASE=0xfe580

def load(p): return json.loads(Path(p).read_text())
def dump(p,x):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def sha(b): return hashlib.sha256(b).hexdigest()
def file_sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        while b:=f.read(8<<20):h.update(b)
    return h.hexdigest()
def put(p,b):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
def words(b):return list(struct.unpack('<'+'I'*(len(b)//4),b[:len(b)//4*4]))
def u32(b,o):return struct.unpack_from('<I',b,o)[0]
def member(v,n):return (WORK/'inputs'/v/n).read_bytes()
def progress(s):print(s,flush=True)

def prepare():
    receipt=WORK/'inputs/snapshot.json'
    if receipt.exists():
        for r in load(receipt)['files']:
            p=WORK/r['path']
            if p.stat().st_size!=r['size'] or file_sha(p)!=r['sha256']:
                raise ValueError(f'frozen input drift: {p}')
        return load(receipt)
    config=load(ROOT/'config/iso/zh-release-current-build.json')
    comp=load(ANALYSIS/'comparison.json');entries=[]
    def save(rel,b):
        target=WORK/'inputs'/rel;put(target,b)
        entries.append({'path':str(target.relative_to(WORK)),'size':len(b),'sha256':sha(b)})
    required={x['member'] for x in config['replacements']}
    # Best edition identity is checked from the full source image.
    for v in ['original','best']:
        iso=Path(comp[v]['path']);progress(f'[snapshot] verify {v} ISO')
        assert file_sha(iso)==comp[v]['hashes']['sha256'],v
        with iso.open('rb') as f:
            for m in comp[v]['members']:
                if m['path'] in required or m['path']=='SLPS_732.70':
                    f.seek(m['extent_lba']*2048);b=f.read(m['size'])
                    assert sha(b)==m['sha256'],(v,m['path'])
                    save(f"{v}/{m['path']}",b)
    for r in config['replacements']:
        b=(ROOT/r['source']).read_bytes()
        assert len(b)==r['size'] and sha(b)==r['sha256'],r['member']
        save('chinese/'+r['member'],b)
    for n in ['comparison.json','function-matches.json','original-functions.json','best-functions.json','resource-differences.json','text-differences.json','migration-audit.json']:
        save('analysis/'+n,(ANALYSIS/n).read_bytes())
    save('current-iso-config.json',json.dumps(config,ensure_ascii=False).encode())
    for n in ['config/encoding/zh-release-font-assignments.json','config/assets/archive-inventory.json','vendor/upstream-python/project/tbl_all.json','vendor/upstream-python/project/menu_files.json']:
        save(n,(ROOT/n).read_bytes())
    for p in sorted((ROOT/'corpus/zh').rglob('*.json')):save(str(p.relative_to(ROOT)),p.read_bytes())
    # Keep helper behavior stable while other tasks edit the Original pipeline.
    for p in sorted((ROOT/'tools/srwz').glob('*.py')):save('tooling/srwz/'+p.name,p.read_bytes())
    result={'schema_version':1,'purpose':'experimental Best migration snapshot; Original outputs unchanged','files':entries,'iso_sources':{v:{'path':comp[v]['path'],'sha256':comp[v]['hashes']['sha256']} for v in ['original','best']},'current_iso_lock':config['output']}
    dump(receipt,result);return result

def normalized_word(w):
    return -1 if 0x100000<=w<0x02000000 else w

def build_address_map():
    a=member('original','SLPS_258.87');b=member('best','SLPS_732.70');c=member('chinese','SLPS_258.87')
    aa=load(WORK/'inputs/analysis/original-functions.json');bb=load(WORK/'inputs/analysis/best-functions.json');matches=load(WORK/'inputs/analysis/function-matches.json')
    amap={};method={}
    def sk(w):
        op=w>>26
        return w&0xfc000000 if op in (2,3) else w if op in (0,0x1c,0x10,0x11,0x12) else w&0xffff0000
    for p in matches['pairs']:
        x,y=aa[p['original_index']]['instructions'],bb[p['best_index']]['instructions']
        if p['skeleton_equal']:
            blocks=[(0,0,len(x))]
        else:
            blocks=[(s.a,s.b,s.size) for s in difflib.SequenceMatcher(None,[sk(i['word']) for i in x],[sk(i['word']) for i in y],autojunk=False).get_matching_blocks()]
        for i,j,n in blocks:
            for u,v in zip(x[i:i+n],y[j:j+n]):
                amap[u['address']-BASE]=v['address']-BASE;method[u['address']-BASE]='function_instruction'
    # Data records are word-aligned; normalize pointers for structural alignment.
    # Every copied data edit is subsequently checked against exact source bytes.
    start=0x2f0000
    x,y=words(a[start:]),words(b[start:])
    sm=difflib.SequenceMatcher(None,[normalized_word(w) for w in x],[normalized_word(w) for w in y],autojunk=True)
    for block in sm.get_matching_blocks():
        for j in range(block.size):
            o=start+4*(block.a+j);n=start+4*(block.b+j)
            if o not in amap:amap[o]=n;method[o]='data_word_alignment'
    # Known instruction omitted by Ghidra's preceding function boundary.
    old=0x15407c-BASE
    needle=a[old-28:old+4];hits=[];pos=b.find(needle)
    while pos>=0:hits.append(pos+28);pos=b.find(needle,pos+1)
    if len(hits)==1:amap[old]=hits[0];method[old]='unique_full_instruction_context'
    # The stock scenario-chart mask lives in the preceding return delay slot.
    assert a[old:old+4]==b[old+0x10:old+0x14]
    amap[old]=old+0x10;method[old]='scenario_chart_delay_slot'
    # Changed archive offset tables cannot be matched by their old values.
    inv=load(WORK/'inputs/config/assets/archive-inventory.json')['archives']
    resources=load(WORK/'inputs/analysis/resource-differences.json')
    for ar in inv:
        if ar['member']=='DATA/COMPDATA.BN':continue
        start,end=int(ar['table_start'],0),int(ar['table_end'],0)+1
        explicit=resources.get(ar['member'],{}).get('table_file_offsets')
        shift=explicit[1]-explicit[0] if explicit else None
        if shift is None:
            deltas=collections.Counter(amap[o]-o for o in range(start,end,4) if o in amap)
            if deltas:shift=deltas.most_common(1)[0][0]
        assert shift is not None,ar['member']
        for o in range(start,end,4):amap[o]=o+shift;method[o]='archive_table:'+ar['member']
    # Official text edits. The shortened skill description is rewritten as a
    # complete Best slot later; never align fragments within its old sentence.
    for o in range(0x336470,0x3364a8,4):amap.pop(o,None)
    for o in [0x33cf0c,0x344724,0x344728]:
        amap[o]=o+0x7f0;method[o]='official_typo_translated_slot'
    missing=[];conflicts=[];changed=[]
    for o in range(0,len(c)-3,4):
        if a[o:o+4]==c[o:o+4]:continue
        if 0x336470<=o<0x3364a8:continue
        n=amap.get(o)
        if n is None:missing.append({'offset':hex(o),'original':a[o:o+4].hex(),'chinese':c[o:o+4].hex()});continue
        changed.append({'original_file_offset':o,'best_file_offset':n,'method':method[o]})
        if a[o:o+4]!=b[n:n+4]:conflicts.append({'original_file_offset':o,'best_file_offset':n,'original':a[o:o+4].hex(),'best':b[n:n+4].hex(),'chinese':c[o:o+4].hex(),'method':method[o]})
    dump(WORK/'address-map.json',{'word_map':{str(k):v for k,v in amap.items()},'changed':changed,'missing':missing,'conflicts':conflicts})
    progress(f'[address map] {len(changed)} changed words mapped; {len(missing)} missing; {len(conflicts)} three-way differences')
    if missing:progress(str(missing[:15]))
    return amap

def init_helpers():
    binary=WORK/'inputs/work/toolchain/srwz-compressor-rs/target/release/srwz-compress'
    if not binary.exists():
        binary.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(ROOT/'work/toolchain/srwz-compressor-rs/target/release/srwz-compress',binary)
        dump(WORK/'native-toolchain.json',{'path':str(binary),'sha256':file_sha(binary)})
    assert file_sha(binary)==load(WORK/'native-toolchain.json')['sha256']
    sys.path.insert(0,str(WORK/'inputs/tooling'))
    from srwz.codec import decode_production,encode
    from srwz.text import load_text_table,PreparedTextEncoder,TextTable
    global decode,compress,TABLE,ENCODER,ZH_TABLE
    decode=decode_production;compress=encode
    TABLE=load_text_table(WORK/'inputs/vendor/upstream-python/project/tbl_all.json')
    ass=load(WORK/'inputs/config/encoding/zh-release-font-assignments.json')
    overrides={x['character']:int(x['code'],16) for x in ass['primary_assignments']}
    # Preserve the production convention: visible ASCII/digits use the stock
    # double-byte glyph, while format/name-control tokens stay raw.
    for ch in '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz':
        overrides[ch]=int.from_bytes(chr(ord(ch)+0xfee0).encode('cp932'),'big')
    overrides[' ']=0x8140
    ENCODER=PreparedTextEncoder(TABLE,overrides)
    chars=dict(TABLE.characters)
    for key in ['primary_assignments','surface_alias_assignments','source_compatibility_assignments']:
        for x in ass[key]:chars[int(x['code'],16)]=x['character']
    ZH_TABLE=TextTable(chars,TABLE.tags)

def offsets(n,v):
    elf=member(v,'SLPS_732.70' if v=='best' else 'SLPS_258.87');data=member(v,n)
    if n=='DATA/STAGE.BIN':return words(member(v,'HEDBDY/HB.BIN')[30320:31144])
    if n=='DATA/COMPDATA.BN':return [0,len(data)]
    inv=load(WORK/'inputs/config/assets/archive-inventory.json')['archives']
    ar=next(x for x in inv if x['member']==n)
    st,en=int(ar['table_start'],0),int(ar['table_end'],0)+1
    if v=='best':
        rr=load(WORK/'inputs/analysis/resource-differences.json').get(n,{})
        if rr.get('table_file_offsets'):st=rr['table_file_offsets'][1];en=st+int(ar['table_end'],0)+1-int(ar['table_start'],0)
        else:
            mapping=load(WORK/'address-map.json')['word_map'];ns=int(mapping[str(st)]);en=ns+(en-st);st=ns
    os=words(elf[st:en]);assert os[0]==0 and all(x<=y for x,y in zip(os,os[1:])),(n,v)
    if os[-1]!=len(data):os.append(len(data))
    return os

def decoded_inputs(n):
    ds={v:member(v,n) for v in ['original','best','chinese']};os={v:offsets(n,v) for v in ds}
    assert len({len(t) for t in os.values()})==1,(n,{v:len(t) for v,t in os.items()})
    for i in range(len(os['original'])-1):
        streams={v:ds[v][os[v][i]:os[v][i+1]] for v in ds}
        if not streams['original'] and not streams['best'] and not streams['chinese']:continue
        yield i,streams,{v:decode(s).output for v,s in streams.items()}

def audit_archives():
    report={}
    for n in ['DATA/COMPDATA.BN','DATA/STAGE.BIN','DATA/NISVDATA.BIN','DATA/HSFC.BIN','DATA/MTVZKNPT.BIN','EFF/VEFF2DX.BIN']:
        rows=[]
        for i,ss,dd in decoded_inputs(n):
            a,b,c=(dd[v] for v in ['original','best','chinese'])
            if a==b:continue
            row={'index':i,'sizes':[len(a),len(b),len(c)],'chinese_changed':a!=c}
            if len(a)==len(b)==len(c):
                conflicts=[];counts=collections.Counter()
                for o in range(0,len(a)-3,4):
                    x,y,z=u32(a,o),u32(b,o),u32(c,o)
                    if x!=y and x!=z:
                        typ='pointer_800' if y-x==0x800 and 0x100000<=x<0x2000000 else 'low_800' if y>>16==x>>16 and ((y-x)&0xffff)==0x800 else 'other'
                        counts[typ]+=1
                        if typ=='other':conflicts.append([o,f'{x:08x}',f'{y:08x}',f'{z:08x}'])
                row['conflict_counts']=dict(counts);row['other_conflicts']=conflicts
            rows.append(row)
        report[n]=rows;progress(f'[archive audit] {n}: {len(rows)} Best-changed chunks; size variants {collections.Counter(tuple(x["sizes"]) for x in rows if len(set(x["sizes"]))>1)}; conflicts {sum(len(x.get("other_conflicts",[])) for x in rows)}')
    dump(WORK/'archive-merge-audit.json',report)

def text_end(data,start,table=None):
    from srwz.text import decode_text
    return decode_text(data,start,table or TABLE).end

def fixed_text(data,start,end,text):
    payload=ENCODER.encode(text,terminate=True)
    assert len(payload)<=end-start,(text,len(payload),end-start)
    data[start:end]=payload+bytes(end-start-len(payload))

def verify_best_elf_policy(native, candidate):
    """Keep the existing all-visible policy and the Best mode initializer."""
    checks=[(0x153e94,0x00a21024,0x00a21025),
            (0x15408c,0x00821024,0x00821025),
            (0x154134,0x00a21024,0x00a21025),
            (0x154454,0x00451024,0x00451025),
            (0x1a3de0,0x0c04e64c,0x0c04e64c),
            (0x1a3f14,0x10430008,0x10000008),
            (0x2016f4,0x80238d72,0x80238d6e),
            (0x3eb260,0x80238d72,0x80238d6e)]
    for address, before, after in checks:
        assert u32(native,address-BASE)==before, ('Best policy source drift',hex(address))
        assert u32(candidate,address-BASE)==after, ('Best policy output drift',hex(address))

def port_elf():
    a=member('original','SLPS_258.87');b=member('best','SLPS_732.70');c=member('chinese','SLPS_258.87');out=bytearray(b)
    audit=load(WORK/'address-map.json');assert not audit['missing']
    rows=[];used=set()
    for r in audit['changed']:
        o,n=r['original_file_offset'],r['best_file_offset']
        if r['method'].startswith('archive_table:'):continue
        assert n not in used,('duplicate ELF destination',hex(n));used.add(n)
        x,y,z=u32(a,o),u32(b,n),u32(c,o)
        if x!=y:
            if r['method']=='function_instruction':
                assert x==0x80238572 and y==0x80238d72 and z==0x8023856e,(hex(o),hex(x),hex(y),hex(z))
                z=0x80238d6e
            else:assert r['method']=='official_typo_translated_slot'
        struct.pack_into('<I',out,n,z);rows.append({**r,'before':f'{y:08x}','after':f'{z:08x}'})
    fixed_text(out,0x336c70,0x336ca0,'援护攻击必定产生暴击。')
    verify_best_elf_policy(b,out)
    dump(WORK/'elf-port-audit.json',rows)
    return out

def port_word_changes(a,b,c,*,shift=0,pointer_delta=0x800,text_mask=None,label=''):
    """Three-way merge; a text mask authorizes whole owned text allocations.

    Non-text overlaps must be proven relocated pointers. Exact unchanged
    preimages can receive the frozen Chinese edit at their mapped location.
    """
    out=bytearray(b);conflicts=[]
    for o in range(0,len(a)-3,4):
        n=o+(shift(o) if callable(shift) else shift)
        if a[o:o+4]==c[o:o+4]:continue
        assert n+4<=len(b),(label,hex(o),shift)
        x,y,z=u32(a,o),u32(b,n),u32(c,o)
        if x!=y and x!=z:
            if 0x100000<=x<0x2000000 and y-x==pointer_delta and 0x100000<=z<0x2000000:z+=pointer_delta
            elif text_mask is not None and all(a[o+j]==b[n+j] or text_mask[o+j] for j in range(4)):pass
            else:conflicts.append([o,n,f'{x:08x}',f'{y:08x}',f'{z:08x}']);continue
        struct.pack_into('<I',out,n,z)
    assert not conflicts,(label,'unresolved three-way overlaps',conflicts[:12])
    return out

@functools.lru_cache(maxsize=3)
def stage_functions(v):
    from srwz.stage import STAGE_FUNCTION_TABLE_START
    st=STAGE_FUNCTION_TABLE_START if v!='best' else load(WORK/'address-map.json')['word_map'][str(STAGE_FUNCTION_TABLE_START)]
    return words(member(v,'SLPS_732.70' if v=='best' else 'SLPS_258.87')[st:st+824])

def parse_candidate_stage(data,v,index):
    from srwz.stage import parse_stage,STAGE_FUNCTION_TABLE_START
    function=stage_functions(v)[index];base=0x7566f0+(0x800 if v=='best' else 0)
    # Adapt only the parser's three global-store signatures in a scratch view;
    # the candidate's actual Best instructions are never normalized.
    if v=='best':
        f=function-base
        if 0<=f<len(data):
            w=data[f:f+200]
            for old,new in [('b05a22ac','b05222ac'),('b85a22ac','b85222ac'),('c05a22ac','c05222ac')]:w=w.replace(bytes.fromhex(old),bytes.fromhex(new))
            data=data[:f]+w+data[f+200:]
    return parse_stage(data,TABLE if v!='chinese' else ZH_TABLE,stage_index=index,function_address=function,base_address=base)

def replace_default_player_name(payload, encoded_default):
    """The native dialogue token is literal ASCII $n, not condition token ':'."""
    assert encoded_default and payload.count(encoded_default)==1, 'player-name preimage drift'
    return payload.replace(encoded_default,b'$n',1)

def port_stage(index,a,b,c):
    from srwz.text import decode_text
    shift=128 if index==26 else 96 if index==161 else 0
    pp={v:parse_candidate_stage(d,v,index) for v,d in [('original',a),('best',b),('chinese',c)]}
    ee={v:{e.entry_id:e for e in p.entries if e.pointer_offset is not None and e.text_offset is not None} for v,p in pp.items()}
    assert set(ee['original'])==set(ee['best'])==set(ee['chinese']),(index,'stage entry identity')
    mask=bytearray(len(a));regions=[]
    for e in ee['original'].values():
        end=text_end(a,e.text_offset);limit=min(len(a),(end+15)//16*16)
        while end<limit and a[end]==0:end+=1
        mask[e.text_offset:end]=b'\1'*(end-e.text_offset);regions.append((e.text_offset,end))
    # Chunk zero has separate fixed-slot system dialogue owners. Its official
    # spelling changes are entirely inside the established Chinese text span.
    if index==0:
        assert all(o>=0x4400 for o in range(0,len(a)-3,4) if a[o:o+4]!=c[o:o+4])
        mask[0x4400:]=b'\1'*(len(a)-0x4400)
    if index in (111,150):
        # Best shrank native strings; the Chinese pool stays in its already
        # validated Original allocation layout. Translate all typed owners.
        tail=min(lo for lo,hi in regions)
        # The subsequent name-label tail is part of the same native text
        # layout; Best shifts it too. Keep the frozen Chinese text layout and
        # validate each existing relocated address into that tail.
        regions=[(tail,len(a))];mask[tail:]=b'\1'*(len(a)-tail)
        adjusted=bytearray(b)
        for lo,hi in regions:adjusted[lo:hi]=a[lo:hi]
        for o in range(0,tail-3,4):
            x,y,z=u32(a,o),u32(b,o),u32(c,o)
            if 0x7566f0+tail<=x<0x7566f0+len(a):
                assert y-x in [0x800,0x7f0,0x7e0,0x6b0],(index,hex(o),'text-tail source relocation',hex(x),hex(y))
                assert 0x7566f0+tail<=z<0x7566f0+len(a)
                struct.pack_into('<I',adjusted,o,x+0x800)
        for k,e in ee['original'].items():
            be=ee['best'][k];assert be.pointer_offset==e.pointer_offset
            struct.pack_into('<I',adjusted,e.pointer_offset,0x756ef0+e.text_offset)
        b_for_merge=bytes(adjusted)
    else:b_for_merge=b
    offset_shift=(lambda o:96 if o<0x1130 else 128) if index==161 else shift
    out=port_word_changes(a,b_for_merge,c,shift=offset_shift,pointer_delta=0x800+shift,text_mask=mask,label=f'STAGE {index}')
    for lo,hi in regions:out[lo+shift:hi+shift]=c[lo:hi]
    if index in (111,150):
        for o in range(0,tail-3,4):
            if 0x7566f0+tail<=u32(a,o)<0x7566f0+len(a):struct.pack_into('<I',out,o,u32(c,o)+0x800)
    # Match every direct owner by parsed entry ID, and carry byte-exact Chinese
    # payloads; the 128-byte code growth applies to both sites and pool targets.
    targets={}
    for k,e in ee['original'].items():
        be,ce=ee['best'][k],ee['chinese'][k]
        assert be.pointer_offset==e.pointer_offset+shift,(index,k,'pointer site')
        dest=ce.text_offset+shift
        payload=c[ce.text_offset:text_end(c,ce.text_offset,ZH_TABLE)]
        assert out[dest:dest+len(payload)]==payload,(index,k,'raw Chinese payload')
        struct.pack_into('<I',out,be.pointer_offset,0x756ef0+dest)
        targets[e.text_offset]=(be.text_offset,ce.text_offset)
    # Existing Chinese alias changes have independently established ownership.
    # Also retain unchanged aliases when Best merely moved its Japanese pool.
    if index in (111,150):
        selected={e.pointer_offset for e in ee['original'].values()}
        for o in range(0,len(a)-3,4):
            if any(mask[o:o+4]) or o in selected:continue
            t=u32(a,o)-0x7566f0
            if t in targets:
                bt,ct=targets[t]
                assert u32(b,o)==0x756ef0+bt,(index,hex(o),'Best alias preimage')
                assert u32(c,o)==0x7566f0+ct,(index,hex(o),'Chinese alias preimage')
                struct.pack_into('<I',out,o,0x756ef0+ct)
    fixes=[]
    for k,e in ee['chinese'].items():
        be=ee['best'][k];dest=u32(out,be.pointer_offset)-0x756ef0
        payload=c[e.text_offset:text_end(c,e.text_offset,ZH_TABLE)]
        new=payload
        if index==84:new=new.replace(ENCODER.encode('劝界'),ENCODER.encode('观界'))
        if index==96:new=new.replace(ENCODER.encode('机动军'),ENCODER.encode('机动群'))
        if k=='story/150/dialogue/01.09/0000':new=replace_default_player_name(new,ENCODER.encode('兰德'))
        assert len(new)<=len(payload)
        if new!=payload:
            out[dest:dest+len(payload)]=new+bytes(len(payload)-len(new));fixes.append(k)
        assert out[dest:dest+len(new)]==new
    assert len(out)==len(b)
    # Full structural reparse verifies the Best code-derived tables and every
    # pointer after relocation. Chinese raw bytes were separately compared.
    check=parse_candidate_stage(bytes(out),'best',index)
    actual_ids={e.entry_id for e in check.entries if e.pointer_offset is not None and e.text_offset is not None}
    assert actual_ids==set(ee['best']),(index,'reparse pointer owner identity',len(actual_ids),len(ee['best']))
    return bytes(out),{'index':index,'entries':len(ee['best']),'localized_data_shift':shift,'decoded_size_growth':len(b)-len(a),'text_fixes':fixes}

def port_compdata(a,b,c):
    mask=bytearray(len(a))
    for lo,hi in [(0x244cc,0x244dc),(0x2457c,0x2458c),(0x6c4c0,0x6c5c0)]:mask[lo:hi]=b'\1'*(hi-lo)
    out=port_word_changes(a,b,c,text_mask=mask,label='COMPDATA')
    # Whole fixed allocations prevent remnants of a longer Best source line.
    fixed_text(out,0x6c4c0,0x6c550,'使2000以下的伤害无效化。\n气力100以上时发动，消耗5EN。\n采用中央队形时，对小队全机生效。')
    from srwz.text import decode_text
    old=decode_text(c,0x6c550,ZH_TABLE).text;assert '10EN' in old or '１０ＥＮ' in old,old
    fixed_text(out,0x6c550,0x6c5e0,old.replace('10EN','5EN').replace('１０ＥＮ','5EN'))
    # Best corrects two NPC faction names. Preserve adjacent record fields.
    for start in [0x244ce,0x2457e]:
        assert b[start:start+2]==bytes.fromhex('8347')
        fixed_text(out,start,start+14,'奥古兵')
    for o in [0x7165,0x59f9e,0x5b02e,0x5d4ff]:assert out[o]==b[o],hex(o)
    return bytes(out)

def port_qa(c):
    from srwz.nisv_strategy_qa import _parse_page
    from srwz.text import decode_text
    start=0xeb70;size=2064;p=_parse_page(c,start,size);records=[];changes=[];active=None
    for j,r in enumerate(p['records']):
        text=decode_text(r['raw']+b'\0',0,ZH_TABLE).text
        if j==23:assert text=='Ｉ力场'
        if j==27:assert text=='屏障力场'
        new=r['raw']
        # Scope the numeric edits to the exact barrier descriptions, not all EN.
        if 'EN' in text or 'ＥＮ' in text:
            if '5' in text or '５' in text:
                if j==25:new=new.replace(ENCODER.encode('5'),ENCODER.encode('10'))
            elif '10' in text or '１０' in text:
                if j==29:new=new.replace(ENCODER.encode('10'),ENCODER.encode('5'))
        if new!=r['raw']:changes.append({'record':j,'heading':active,'before':text,'after':decode_text(new+b'\0',0,ZH_TABLE).text})
        records.append(r['header']+new+b'\0')
    assert len(changes)==2,('Q&A expected two corrections',changes,[(decode_text(r['raw']+b'\0',0,ZH_TABLE).text) for r in p['records']])
    section=b''.join(records);payload=struct.pack('<H',len(section))+section+struct.pack('<H',p['sprite_size'])+p['sprite_bytes']
    assert len(payload)<=size
    out=bytearray(c);out[start:start+size]=payload+bytes(size-len(payload));_parse_page(out,start,size)
    dump(WORK/'qa-text-fixes.json',changes);return bytes(out)

def port_zkan(a,b,c,actor_bytes=None):
    from srwz.library import parse_zkn_decoded_chunk,parse_runtime_zkn_decoded_chunk,zkan_escape_transform
    aa,bb=[parse_zkn_decoded_chunk(d) for d in [a,b]];cc=parse_runtime_zkn_decoded_chunk(c,ZH_TABLE)
    assert [f.tag for f in aa.fields]==[f.tag for f in bb.fields]==[f.tag for f in cc.fields]
    records=bytearray()
    for x,y,z in zip(aa.fields,bb.fields,cc.fields):
        raw=z.data
        if x.data!=y.data:
            if x.tag=='VOIC':raw=y.data
            elif x.tag=='ACTR':assert actor_bytes is not None;raw=actor_bytes
            else:raise ValueError(('unexpected ZKAN Best change',x.tag))
        records.extend(x.tag.encode());records.extend(struct.pack('<I',len(raw)));records.extend(raw)
    payload=b'ZKAN'+cc.kind.encode()+struct.pack('<II',cc.version,12)+b'DSIZ'+struct.pack('<I',len(records)+8)+b'DATA'+struct.pack('<I',len(records))+records
    payload+=bytes((-len(payload))%16)
    out=struct.pack('<8I',1,32,0,len(payload),len(payload),0,0,0)+zkan_escape_transform(payload)
    doc=parse_runtime_zkn_decoded_chunk(out,ZH_TABLE)
    for f in doc.fields:
        if f.tag=='VOIC':assert f.data==bb.field('VOIC').data
    return out

def port_srvc():
    from srwz.srvc import parse_srvc_archive,parse_srvc_archive_with_layout
    aa,bb,cc=[member(v,'BTL/SRVC.BIN') for v in ['original','best','chinese']]
    oo={v:tuple(words(member(v,'BTL/SRVC.SEG'))) for v in ['original','best','chinese']}
    pa=parse_srvc_archive(aa,oo['original'],TABLE);pb=parse_srvc_archive(bb,oo['best'],TABLE)
    pc=parse_srvc_archive_with_layout(cc,oo['chinese'],pa,ZH_TABLE)
    bytext={};ambiguous=[]
    for x,z in zip(pa,pc):
        assert len(x.records)==len(z.records)
        for ar,cr in zip(x.records,z.records):
            payload=cc[cr.archive_text_start:cr.archive_text_end]
            if ar.text in bytext and bytext[ar.text]!=payload:ambiguous.append(ar.text)
            bytext[ar.text]=payload
    assert not ambiguous,('SRVC duplicate translations differ',ambiguous[:5])
    audit=load(WORK/'inputs/analysis/migration-audit.json');fixes=[]
    overrides={
        'battle/08976':'“不能再让你们兄弟为所欲为！”',
        'battle/18550':'“啊哈哈哈！大意了吧！”',
        'battle/21728':'“∀的话，是倒X的哥哥吧！”',
    }
    # Corpus IDs contain their own prefix; select their trailing numeric part.
    for r in audit['battle_source_migrations']:
        payload=bytext.get(r['best'],bytext[r['original']])
        number=r['old_id'].rsplit(':',1)[-1]
        chosen=next((s for k,s in overrides.items() if k.endswith(number)),None)
        if chosen:payload=ENCODER.encode(chosen.replace('\\n','{5C}{6E}'),terminate=True);fixes.append({'id':r['old_id'],'translation':chosen})
        bytext[r['best']]=payload
    out=bytearray(bb);count=0;headroom=[]
    for ch in pb:
        if not ch.records:continue
        ps=[];cursor=0
        for r in ch.records:
            payload=bytext[r.text];assert payload.endswith(b'\0')
            struct.pack_into('<I',out,ch.archive_start+ch.text_index_start+r.record_index*8+4,cursor)
            cursor+=len(payload);ps.append(payload);count+=1
        capacity=ch.indexed_text_end-ch.text_pool_start
        assert cursor<=capacity,(ch.chunk_index,'SRVC overflow',cursor,capacity)
        st=ch.archive_start+ch.text_pool_start;en=ch.archive_start+ch.indexed_text_end
        out[st:en]=b''.join(ps)+bytes(capacity-cursor);headroom.append(capacity-cursor)
        assert out[en:ch.archive_end]==bb[en:ch.archive_end]
    check=parse_srvc_archive_with_layout(bytes(out),oo['best'],pb,ZH_TABLE)
    for x,y in zip(pb,check):
        assert len(x.records)==len(y.records)
        for s,t in zip(x.records,y.records):
            assert s.metadata==t.metadata
            assert out[t.archive_text_start:t.archive_text_end]==bytext[s.text]
    assert count==58751,count
    dump(WORK/'srvc-port-audit.json',{'records':count,'minimum_chunk_headroom':min(headroom),'text_fixes':fixes,'best_nontext_metadata_and_tail_preserved':True})
    return bytes(out)

def encoded_chunk(target,streams,decoded):
    for v in ['best','chinese','original']:
        if target==decoded[v]:
            r=decode(streams[v]);return streams[v][:r.consumed]
    r=decode(streams['best'])
    encoded=compress(target,strategy='rust-fit',flags=r.flags,
        header_unknown_0=r.metadata.get('header_unknown_0'),header_unknown_1=r.metadata.get('header_unknown_1',0))
    assert decode(encoded).output==target
    return encoded

def pack_archive(n,items):
    """Pack aligned streams within the exact Best member byte capacity."""
    best=member('best',n);original_offsets=offsets(n,'best');parts=[];table=[0];rows=[]
    for i,payload,target in items:
        assert i==len(parts),(n,'chunk sequence',i,len(parts))
        parts.append(payload+bytes((-len(payload))%16));table.append(table[-1]+len(parts[-1]))
        rows.append({'index':i,'encoded_size':len(payload),'decoded_size':len(target),'decoded_sha256':sha(target)})
    logical_size=table[-1]
    assert logical_size<=len(best),(n,'Best member capacity',logical_size,len(best))
    result=b''.join(parts)+bytes(len(best)-logical_size)
    table[-1]=len(best)
    for (i,_payload,target),lo,hi in zip(items,table,table[1:]):assert decode(result[lo:hi]).output==target,(n,i,'packed readback')
    put(WORK/'components'/n,result)
    dump(WORK/'archives'/f'{n.replace("/","_")}.json',{'member':n,'member_size':len(best),'logical_size_before_tail_padding':logical_size,'remaining_bytes':len(best)-logical_size,'offsets':table,'chunks':rows})
    progress(f'[archive] {n}: {len(items)} chunks, {len(best)-logical_size} bytes free')
    return table

def assemble_components():
    from srwz.library import parse_runtime_zkn_decoded_chunk
    elf=port_elf();tables={};stage_rows=[]
    cfg=load(WORK/'inputs/current-iso-config.json');changes=set(load(WORK/'inputs/analysis/migration-audit.json')['summary']['replacements']['changed_in_best'])
    # Same-source archives and reviewed image resources are reused byte-exact.
    for r in cfg['replacements']:
        n=r['member']
        if n in changes or n.startswith('SLPS_'):continue
        data=member('chinese',n);best=member('best',n);assert len(data)<=len(best)
        put(WORK/'components'/n,data+bytes(len(best)-len(data)))
    for n in ['DATA/COMPDATA.BN','DATA/STAGE.BIN','DATA/NISVDATA.BIN','DATA/HSFC.BIN','DATA/MTVZKNPT.BIN','EFF/VEFF2DX.BIN']:
        prepared=[];actor={}
        if n=='DATA/MTVZKNPT.BIN':
            data=member('chinese',n);os=offsets(n,'chinese')
            for i in [407,408]:actor[i]=parse_runtime_zkn_decoded_chunk(decode(data[os[i]:os[i+1]]).output,ZH_TABLE).field('ACTR').data
        for i,ss,dd in decoded_inputs(n):
            a,b,c=[dd[v] for v in ['original','best','chinese']]
            if n=='DATA/STAGE.BIN':target,row=port_stage(i,a,b,c);stage_rows.append(row)
            elif n=='DATA/COMPDATA.BN':target=port_compdata(a,b,c)
            elif n=='DATA/NISVDATA.BIN' and i==6:target=port_qa(c)
            elif a==b:target=c
            elif a==c:target=b
            elif n=='DATA/MTVZKNPT.BIN':target=port_zkan(a,b,c,actor.get(815-i))
            elif n=='EFF/VEFF2DX.BIN':target=bytes(port_word_changes(a,b,c,label=f'{n}/{i}'))
            else:raise ValueError(('unhandled archive merge',n,i))
            prepared.append((i,ss,dd,target))
        def work(row):
            i,ss,dd,target=row
            cache=WORK/'compressed-cache'/sha(target+ss['best'][:16])
            if cache.exists():
                payload=cache.read_bytes();assert decode(payload).output==target
            else:payload=encoded_chunk(target,ss,dd);put(cache,payload)
            return i,payload,target
        with ThreadPoolExecutor(max_workers=4) as pool:items=list(pool.map(work,prepared))
        if n=='DATA/COMPDATA.BN':
            payload=items[0][1];assert len(payload)<=len(member('best',n));out=payload+bytes(len(member('best',n))-len(payload))
            put(WORK/'components'/n,out);assert decode(out).output==items[0][2]
            dump(WORK/'archives/DATA_COMPDATA.BN.json',{'member':n,'encoded_size':len(payload),'decoded_sha256':sha(items[0][2]),'member_size':len(out)});progress('[archive] COMPDATA readback passed')
        else:tables[n]=pack_archive(n,items)
    dump(WORK/'stage-port-audit.json',stage_rows)
    put(WORK/'components/BTL/SRVC.BIN',port_srvc());put(WORK/'components/BTL/SRVC.SEG',member('best','BTL/SRVC.SEG'))
    hb=bytearray(member('best','HEDBDY/HB.BIN'));hb[30320:31144]=struct.pack('<206I',*tables.pop('DATA/STAGE.BIN'));put(WORK/'components/HEDBDY/HB.BIN',hb)
    amap=load(WORK/'address-map.json')['word_map']
    for ar in load(WORK/'inputs/config/assets/archive-inventory.json')['archives']:
        n=ar['member']
        if n=='DATA/COMPDATA.BN' or not (WORK/'components'/n).exists():continue
        table=tables.get(n)
        if table is None:
            table=offsets(n,'chinese');table[-1]=len(member('best',n))
        old_st=int(ar['table_start'],0);count=(int(ar['table_end'],0)+1-old_st)//4
        assert len(table) in [count,count+1],(n,len(table),count)
        # Some native tables contain only starts; their terminal size comes
        # from the archive member, while other tables include an end sentinel.
        st=amap[str(old_st)];elf[st:st+4*count]=struct.pack('<'+'I'*count,*table[:count])
    put(WORK/'components/SLPS_732.70',elf)
    files=[]
    for r in cfg['replacements']:
        n='SLPS_732.70' if r['member'].startswith('SLPS_') else r['member'];p=WORK/'components'/n
        assert p.stat().st_size==len(member('best',n))
        files.append({'member':n,'path':str(p),'size':p.stat().st_size,'sha256':file_sha(p)})
    dump(WORK/'component-manifest.json',{'schema_version':1,'edition':'Best','status':'experimental-static-candidate','components':files,'runtime':'pending'})
    progress('[components] 23 Best-sized replacements ready')

def build_iso():
    import os
    manifest=load(WORK/'component-manifest.json');comp=load(WORK/'inputs/analysis/comparison.json')
    src=Path(comp['best']['path']);assert file_sha(src)==comp['best']['hashes']['sha256']
    output=ROOT/'build/iso/best-alpha1/srwz-zh-best-alpha1.iso';output.parent.mkdir(parents=True,exist_ok=True)
    temp=output.with_suffix('.iso.tmp');shutil.copyfile(src,temp)
    native={r['path']:r for r in comp['best']['members']};replacements={r['member']:r for r in manifest['components']}
    with temp.open('r+b') as f:
        for n,r in replacements.items():
            d=Path(r['path']).read_bytes();assert len(d)==native[n]['size']==r['size'] and sha(d)==r['sha256']
            f.seek(native[n]['extent_lba']*2048);f.write(d)
        f.flush();os.fsync(f.fileno())
    # Exact Best file sizes leave ISO9660, UDF, VMAP and all following LBAs
    # untouched. Full member readback checks both changed and native resources.
    readback=[]
    with temp.open('rb') as f:
        for n,r in native.items():
            f.seek(r['extent_lba']*2048);h=hashlib.sha256();remaining=r['size']
            while remaining:
                data=f.read(min(8<<20,remaining));assert data;h.update(data);remaining-=len(data)
            expected=replacements[n]['sha256'] if n in replacements else r['sha256']
            assert h.hexdigest()==expected,(n,'ISO readback')
            readback.append({'member':n,'sha256':expected,'source':'Chinese Best candidate' if n in replacements else 'Best original'})
    assert temp.stat().st_size==src.stat().st_size
    digest=file_sha(temp);temp.replace(output)
    receipt={'schema_version':1,'output':str(output),'size':output.stat().st_size,'sha256':digest,'base_iso_sha256':comp['best']['hashes']['sha256'],'files_verified':len(readback),'replacements':len(replacements),'fixed_best_member_sizes_and_lbas':True,'runtime':'pending','files':readback}
    dump(WORK/'iso-readback.json',receipt);dump(output.parent/'build-receipt.json',receipt)
    progress(f'[ISO] {output}\n[SHA256] {digest}\n[readback] all {len(readback)} files passed')

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--prepare-only',action='store_true');ap.add_argument('--audit',action='store_true');ap.add_argument('--components',action='store_true');ap.add_argument('--iso-only',action='store_true');args=ap.parse_args()
    prepare()
    if not args.prepare_only and not args.iso_only:build_address_map()
    if args.audit:init_helpers();audit_archives()
    if args.components:init_helpers();assemble_components()
    if args.iso_only:build_iso()
    return 0
if __name__=='__main__':raise SystemExit(main())
