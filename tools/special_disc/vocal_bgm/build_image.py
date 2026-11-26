from pathlib import Path
import sys,struct,json,subprocess,hashlib

PLAYER_BASE=0x8c0000
# v1-v5 reserved 0x8c0000-0xdc0000 (the whole song lived in EE memory).
LEGACY_RESERVE_END=0xdc0000

def reserve_end(symbols):
    """End of the player reserve: the payload's __end rounded up to 64 KiB, at least 0xa00000.

    The native heap starts here. The heap setup also uses end-0x10000, which must lie
    above the payload."""
    end=max(0xa00000,(symbols['__end']+0x1ffff)&~0xffff)
    assert symbols['__end']<end-0x10000,'Native heap initialization would overlap payload'
    return end

def heap_addresses(game):
    if game=='sp':return [0x1001d0,0x1410f4,0x44e734]
    return [0x1001d0,0x1001d8,0x140644,0x140650,(0x3f4734 if game=='best' else 0x3f3fb4)]

def heap_words(game,end):
    lui=0x3c040000|((end-0x10000)>>16)
    return [lui,lui,end] if game=='sp' else [lui,0x24840000,lui,0x24840000,end]

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
    bezel_base = 0x8c0000 if game == 'sp' else 0x7a0000
    wide = any(t == 1 and va == bezel_base and n == 0x8c10 and
               b[offset:offset+8] == b'SRWZAR01' for t,offset,va,_,n,*_ in headers)
    relocated = wide and game == 'sp'
    variant = '-wide' if relocated and (W/'symbols-wide.txt').is_file() else ''
    player_base = 0x8e0000 if relocated else PLAYER_BASE
    symbols={l.split()[2]:int(l.split()[0],16) for l in (W/f'symbols{variant}.txt').read_text().splitlines() if len(l.split())==3}
    if symbols.get('__player_base', PLAYER_BASE) != player_base:
        raise ValueError('Music player link address differs from its load address')
    if 'BGM/VOCAL.BIN' in ms:return update_existing_image(W,src,dst,ms,b,headers,symbols,profile,game,music_prefix,replace,player_base,variant)
    for a,old,name in profile['hooks']:patch(a,old,[0x08000000|(symbols[name]>>2),0])
    # Retain the existing gallery reserve and move the native heap's lower boundary up to the player's end.
    end=reserve_end(symbols)
    addresses=heap_addresses(game)
    heap=tuple(struct.unpack_from('<I',b,off(a))[0] for a in addresses)
    if game=='sp':
        allowed=[(0x3c040082,0x3c040082,0x81c600),(0x3c04008b,0x3c04008b,0x8c0000)]
    else:
        allowed=[(0x3c040079,0x2484a500,0x3c040079,0x2484a500,0x78a500) if game=='best' else (0x3c040079,0x24849d00,0x3c040079,0x24849d00,0x789d00),(0x3c04008b,0x24840000,0x3c04008b,0x24840000,0x8c0000),
                 # Chinese builds: the event-caption payload at 0x790000 already moved the heap to 0x7a0000.
                 (0x3c04007a,0x24840000,0x3c04007a,0x24840000,0x7a0000)]
    if wide:
        if game == 'sp':
            allowed.append((0x3c04008d,0x3c04008d,0x8d8c10))
            for address in (0x1001d8,0x141100):
                patch(address,[0x24848c10],[0x24840000])
        else:
            allowed.append((0x3c04007b,0x24848c10,0x3c04007b,0x24848c10,0x7a8c10))
    if heap not in allowed:raise ValueError('Unsupported '+game+' heap layout: '+repr(heap))
    for a,old,new in zip(addresses,heap,heap_words(game,end)):patch(a,[old],[new])
    for t,o,v,p,n,mem,fl,al in headers:
        if t==1 and max(v,player_base)<min(v+mem,end):raise ValueError('Existing executable segment overlaps the music player reserve')
    b,headers=make_header_room(b,ph,num,headers)
    payload=(W/f'payload{variant}.bin').read_bytes();fileoff=(len(b)+4095)&~4095;b+=bytes(fileoff-len(b))+payload
    assert ph+(num+1)*32<=min(x[1] for x in headers if x[4])
    struct.pack_into('<8I',b,ph+num*32,1,fileoff,player_base,player_base,len(payload),end-player_base,7,64);struct.pack_into('<H',b,44,num+1)
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

def make_header_room(b,ph,num,headers):
    """Free one program-header slot by moving file data back by whole alignment units.

    Chinese Original/Best ELFs already used the spare slot (event captions) and the
    end marker (proportional text). Every p_offset moves by the same multiple of the
    largest p_align, so each segment still loads the same bytes at the same address.
    """
    first=min(h[1] for h in headers if h[4]);need=ph+(num+1)*32
    if need<=first:return b,headers
    if struct.unpack_from('<I',b,32)[0] or struct.unpack_from('<H',b,48)[0]:raise ValueError('Cannot move ELF data with a section header table')
    if any(b[ph+num*32:first]):raise ValueError('Unexpected data after the program header table')
    if any(h[1]<first for h in headers):raise ValueError('Program header offset precedes the first file data')
    unit=max([16]+[h[7] for h in headers]);delta=(need-first+unit-1)//unit*unit
    if any(h[7] and (h[1]+delta-h[2])%h[7] for h in headers):raise ValueError('Moved segment would break alignment')
    b=bytearray(b[:first])+bytes(delta)+b[first:]
    headers=[(t,o+delta,*rest) for t,o,*rest in headers]
    for i,h in enumerate(headers):struct.pack_into('<8I',b,ph+i*32,*h)
    return b,headers

def update_existing_image(W,src,dst,ms,b,headers,symbols,profile,game,prefix,replace,player_base=PLAYER_BASE,variant=""):
    """Update only the reserved container when the installed player matches exactly."""
    from container import CAPACITY,validate_prefix,build_prefix
    from special_disc.iso_relocation import verify_untouched,append_members,verify_relocation
    prefix=prefix if prefix is not None else build_prefix(None);validate_prefix(prefix)
    if len(prefix)!=struct.unpack_from('<I',prefix,32)[0]:raise ValueError('Incomplete music container')
    payload=(W/f'payload{variant}.bin').read_bytes()
    segment=next((h for h in headers if h[0]==1 and h[2]==player_base),None)
    if segment is None:raise ValueError('缺少播放器保留区')
    installed=bytes(b[segment[1]:segment[1]+segment[4]])
    current=segment[4]==len(payload) and installed==payload
    from profiles import LEGACY_PLAYERS
    digest=hashlib.sha256(installed).hexdigest()
    legacy=None if current else next((p for p in LEGACY_PLAYERS[game] if segment[4]==p['size'] and digest==p['sha256']),None)
    upgrade=legacy is not None
    if not current and not upgrade:raise ValueError('播放器版本不匹配，请从原盘或汉化基础镜像重新安装')
    reserve=reserve_end(symbols)
    # Legacy entries may name their own reserve end; v1-v5 all used LEGACY_RESERVE_END.
    installed_end=legacy.get('reserve_end',LEGACY_RESERVE_END) if upgrade else reserve
    if segment[5]!=installed_end-player_base:raise ValueError('播放器保留区大小不匹配')
    installed_symbols=legacy['hooks'] if upgrade else symbols
    if any(h is not segment and h[0]==1 and max(h[2],segment[2])<min(h[2]+h[5],segment[2]+segment[5]) for h in headers):raise ValueError('Installed player reserve overlaps another executable segment')
    def off(a):
        for t,o,v,p,n,*_ in headers:
            if t==1 and v<=a<a+8<=v+n:return o+a-v
        raise ValueError('Unsupported installed executable')
    for a,_,name in profile['hooks']:
        if struct.unpack_from('<2I',b,off(a))!=(0x08000000|(installed_symbols[name]>>2),0):raise ValueError('Installed music hook was modified')
    def word(a):
        for t,o,v,p,n,*_ in headers:
            if t==1 and v<=a<a+4<=v+n:return o+a-v
        raise ValueError('Unsupported installed executable')
    if player_base != PLAYER_BASE and any(struct.unpack_from('<I',b,word(a))[0] != 0x24840000 for a in (0x1001d8,0x141100)):
        raise ValueError('Installed SP heap low word was modified')
    if [struct.unpack_from('<I',b,word(a))[0] for a in heap_addresses(game)]!=heap_words(game,installed_end):raise ValueError('Installed heap boundary was modified')
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
        # Shrink the reserve to the new player and give the rest back to the native heap.
        for address,word_value in zip(heap_addresses(game),heap_words(game,reserve)):struct.pack_into('<I',b,word(address),word_value)
        b=b[:segment[1]]+payload
        new_segment=list(segment);new_segment[4]=len(payload);new_segment[5]=reserve-player_base
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
    out=dict(game=game,executable=profile['executable'],source=str(src),iso=str(dst),update_existing=True,player_upgraded=upgrade,upgraded_from=legacy['version'] if upgrade else None,private_end=reserve,relocation=relocation,readback=readback,elf_sha256=hashlib.sha256(b).hexdigest(),payload_bytes=len(payload),symbols={n:symbols[n] for n in ['hook_update','hook_load','hook_native','telemetry','__end']},original_bgm_unchanged=True,music=dict(path='BGM/VOCAL.BIN',lba=member.extent_lba,capacity=CAPACITY,used=len(prefix)),untouched=untouched)
    (W/'build-receipt.json').write_text(json.dumps(out,indent=2)+'\n');return out
