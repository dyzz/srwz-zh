from pathlib import Path
import sys,struct,json,subprocess,hashlib

def build_image(W: Path, src: Path, dst: Path, replace=False, music_prefix=None, game="sp"):
    R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'tools'))
    if dst.parent.resolve() != (R/'build/iso/test').resolve():raise ValueError('Output must be under build/iso/test')
    if src.resolve()==dst.resolve():raise ValueError('Source and candidate must differ')
    from srwz.iso9660 import member_map,scan_iso9660
    from special_disc.iso_relocation import append_members,verify_relocation,verify_untouched
    ms=member_map(scan_iso9660(src))
    def read(name):
     m=ms[name]
     with src.open('rb') as f:f.seek(m.extent_lba*2048);return f.read(m.size)
    from profiles import PROFILES
    profile=PROFILES[game];exe=profile['executable']
    b=bytearray(read(exe));ph=struct.unpack_from('<I',b,28)[0];num=struct.unpack_from('<H',b,44)[0];headers=[struct.unpack_from('<8I',b,ph+i*32) for i in range(num)]
    def off(a):
     for t,o,v,p,n,m,fl,al in headers:
      if t==1 and v<=a<v+n:return o+a-v
     raise ValueError(hex(a))
    def patch(a,expect,words):
     o=off(a);old=struct.unpack_from('<'+'I'*len(expect),b,o);assert old==tuple(expect),(hex(a),old,expect)
     struct.pack_into('<'+'I'*len(words),b,o,*words)
    symbols={l.split()[2]:int(l.split()[0],16) for l in (W/'symbols.txt').read_text().splitlines() if len(l.split())==3}
    if 'BGM/VOCAL.BIN' in ms:return update_existing_image(W,src,dst,ms,b,headers,symbols,profile,game,music_prefix,replace)
    for a,old,name in profile['hooks']:patch(a,old,[0x08000000|(symbols[name]>>2),0])
    # Retain the existing gallery reserve and extend the native heap's lower boundary.
    end=0xdc0000;assert symbols['__end']<end
    if game=='sp':
        heap=tuple(struct.unpack_from('<I',b,off(a))[0] for a in [0x1001d0,0x1410f4,0x44e734])
        if heap not in [(0x3c040082,0x3c040082,0x81c600),(0x3c04008b,0x3c04008b,0x8c0000)]:raise ValueError('Unsupported SP heap layout')
        for a,old,new in zip([0x1001d0,0x1410f4,0x44e734],heap,[0x3c0400db,0x3c0400db,end]):patch(a,[old],[new])
    else:
        assert symbols['__end']<0xdb0000,'Z native heap initialization would overlap payload'
        addresses=[0x1001d0,0x1001d8,0x140644,0x140650,(0x3f4734 if game=='best' else 0x3f3fb4)]
        heap=tuple(struct.unpack_from('<I',b,off(a))[0] for a in addresses)
        allowed=[(0x3c040079,0x2484a500,0x3c040079,0x2484a500,0x78a500) if game=='best' else (0x3c040079,0x24849d00,0x3c040079,0x24849d00,0x789d00),(0x3c04008b,0x24840000,0x3c04008b,0x24840000,0x8c0000)]
        if heap not in allowed:raise ValueError('Unsupported '+game+' heap layout: '+repr(heap))
        for a,old,new in zip(addresses,heap,[0x3c0400db,0x24840000,0x3c0400db,0x24840000,end]):patch(a,[old],[new])
    for t,o,v,p,n,mem,fl,al in headers:
        if t==1 and max(v,0x8c0000)<min(v+mem,end):raise ValueError('Existing executable segment overlaps the music player reserve')
    payload=(W/'payload.bin').read_bytes();fileoff=(len(b)+4095)&~4095;b+=bytes(fileoff-len(b))+payload
    assert ph+(num+1)*32<=min(x[1] for x in headers if x[4])
    struct.pack_into('<8I',b,ph+num*32,1,fileoff,0x8c0000,0x8c0000,len(payload),end-0x8c0000,7,64);struct.pack_into('<H',b,44,num+1)
    if dst.exists():
     if not replace:raise FileExistsError('Use --replace for an existing test candidate')
     dst.unlink()
    subprocess.run(['cp','-c',str(src),str(dst)],check=True)
    rec=append_members(dst,ms,{exe:bytes(b)},catalog_policy='inherit',allowed_udf=None if game=='sp' else {exe,'EFF/VEFF2DX.BIN'});verify=verify_relocation(dst,ms,{exe:bytes(b)},rec)
    from iso_member import add_music
    from container import CAPACITY,build_prefix
    music=add_music(dst,music_prefix if music_prefix is not None else build_prefix(None),CAPACITY)
    out=dict(game=game,executable=exe,source=str(src),iso=str(dst),elf_sha256=hashlib.sha256(b).hexdigest(),source_elf_sha256=hashlib.sha256(read(exe)).hexdigest(),payload_bytes=len(payload),private_end=end,symbols={n:symbols[n] for n in ['hook_update','hook_load','hook_loaded','telemetry','__end']},original_bgm_unchanged=True,music=music,relocation=rec,readback=verify)
    out['untouched']=verify_untouched(src,dst,rec['touched_spans']+[(a,min(z,src.stat().st_size)) for a,z in music['metadata_spans'] if a<src.stat().st_size])
    (W/'build-receipt.json').write_text(json.dumps(out,indent=2)+'\n');print(out['symbols'],len(b),music['lba'])

def update_existing_image(W,src,dst,ms,b,headers,symbols,profile,game,prefix,replace):
    """Update only the reserved container when the installed player matches exactly."""
    from container import CAPACITY,validate_prefix,build_prefix
    from special_disc.iso_relocation import verify_untouched,append_members,verify_relocation
    prefix=prefix if prefix is not None else build_prefix(None);validate_prefix(prefix)
    if len(prefix)!=struct.unpack_from('<I',prefix,32)[0]:raise ValueError('Incomplete music container')
    payload=(W/'payload.bin').read_bytes()
    segment=next((h for h in headers if h[0]==1 and h[2]==0x8c0000),None)
    if segment is None:raise ValueError('缺少播放器保留区')
    installed=bytes(b[segment[1]:segment[1]+segment[4]])
    current=segment[4]==len(payload) and installed==payload
    from profiles import LEGACY_PLAYERS,LEGACY_HOOKS
    legacy=LEGACY_PLAYERS[game]
    upgrade=not current and segment[4]==legacy['size'] and hashlib.sha256(installed).hexdigest()==legacy['sha256']
    if not current and not upgrade:raise ValueError('播放器版本不匹配，请从原盘或汉化基础镜像重新安装')
    if segment[5]!=0x500000 or symbols['__end']>segment[2]+segment[5]:raise ValueError('播放器保留区大小不匹配')
    installed_symbols=LEGACY_HOOKS if upgrade else symbols
    if any(h is not segment and h[0]==1 and max(h[2],segment[2])<min(h[2]+h[5],segment[2]+segment[5]) for h in headers):raise ValueError('Installed player reserve overlaps another executable segment')
    def off(a):
        for t,o,v,p,n,*_ in headers:
            if t==1 and v<=a<a+8<=v+n:return o+a-v
        raise ValueError('Unsupported installed executable')
    for a,_,name in profile['hooks']:
        if struct.unpack_from('<2I',b,off(a))!=(0x08000000|(installed_symbols[name]>>2),0):raise ValueError('Installed music hook was modified')
    member=ms['BGM/VOCAL.BIN'];start=member.extent_lba*2048;end=start+member.size
    if member.size!=CAPACITY:raise ValueError('Unsupported container capacity')
    for name,m in ms.items():
        if name!='BGM/VOCAL.BIN' and m.size and max(start,m.extent_lba*2048)<min(end,m.extent_lba*2048+m.size):raise ValueError('Music container overlaps another file')
    if dst.exists():
        if not replace:raise FileExistsError('Output already exists')
        dst.unlink()
    subprocess.run(['cp','-c',str(src),str(dst)],check=True)
    relocation=None;readback=None
    if upgrade:
        if segment[1]+segment[4]!=len(b):raise ValueError('旧播放器之后存在未知的 ELF 数据')
        for address,_,name in profile['hooks']:struct.pack_into('<2I',b,off(address),0x08000000|(symbols[name]>>2),0)
        b=b[:segment[1]]+payload
        new_segment=list(segment);new_segment[4]=len(payload)
        ph=struct.unpack_from('<I',b,28)[0];struct.pack_into('<8I',b,ph+headers.index(segment)*32,*new_segment)
        relocation=append_members(dst,ms,{profile['executable']:bytes(b)},catalog_policy='inherit',allowed_udf=None if game=='sp' else {profile['executable'],'EFF/VEFF2DX.BIN'})
        readback=verify_relocation(dst,ms,{profile['executable']:bytes(b)},relocation)
    with dst.open('r+b') as f:
        f.seek(start);f.write(prefix);zero=bytes(8*1024*1024);pos=start+len(prefix)
        while pos<end:
            n=min(len(zero),end-pos);f.seek(pos);old=f.read(n)
            if old!=zero[:n]:f.seek(pos);f.write(zero[:n])
            pos+=n
        f.flush();f.seek(start);assert f.read(len(prefix))==prefix
    untouched=verify_untouched(src,dst,[(start,end)]+(relocation['touched_spans'] if relocation else []))
    out=dict(game=game,executable=profile['executable'],source=str(src),iso=str(dst),update_existing=True,player_upgraded=upgrade,relocation=relocation,readback=readback,elf_sha256=hashlib.sha256(b).hexdigest(),payload_bytes=len(payload),symbols={n:symbols[n] for n in ['hook_update','hook_load','hook_native','telemetry','__end']},original_bgm_unchanged=True,music=dict(path='BGM/VOCAL.BIN',lba=member.extent_lba,capacity=CAPACITY,used=len(prefix)),untouched=untouched)
    (W/'build-receipt.json').write_text(json.dumps(out,indent=2)+'\n');return out
