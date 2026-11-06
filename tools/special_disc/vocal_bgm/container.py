"""Version 1 SP music container; all offsets are relative to VOCAL.BIN."""
from __future__ import annotations
import struct,zlib,json,subprocess
from pathlib import Path
MAGIC=b'SRWZVOC1'
CAPACITY=512*1024*1024
HEADER=2048
SLOTS=256
ENTRY=64
DATA=HEADER+SLOTS*ENTRY
PROFILE=0x53500001
MAX_TRACK=4*1024*1024

def build_prefix(ogg: bytes|None, frames=0, track=19):
    table=bytearray(SLOTS*ENTRY)
    for i in range(SLOTS):struct.pack_into('<I',table,i*ENTRY,i)
    used=DATA
    if ogg is not None:
        if not ogg.startswith(b'OggS') or not 0<len(ogg)<=MAX_TRACK:raise ValueError('invalid track input')
        if not 0<=track<SLOTS or not 0<frames<2**32:raise ValueError('invalid track metadata')
        struct.pack_into('<16I',table,track*ENTRY,track,1,DATA,len(ogg),48000,2,frames,0,frames,0x4800,zlib.crc32(ogg),0,0,0,0,0)
        used=(DATA+len(ogg)+2047)&~2047
    h=bytearray(HEADER);h[:8]=MAGIC
    struct.pack_into('<14I',h,8,1,HEADER,HEADER,ENTRY,SLOTS,DATA,used,CAPACITY,PROFILE,zlib.crc32(table),0,0,0,0)
    struct.pack_into('<I',h,48,zlib.crc32(h))
    return bytes(h+table)+(ogg or b'')+bytes(used-DATA-len(ogg or b''))

def validate_prefix(data):
    if len(data)<DATA or data[:8]!=MAGIC:raise ValueError('bad header')
    v=struct.unpack_from('<14I',data,8)
    if v[0] not in (1,2) or v[1:6]!=(HEADER,HEADER,ENTRY,SLOTS,DATA) or v[7]!=CAPACITY or v[8]!=(PROFILE if v[0]==1 else 0x53500002):raise ValueError('unsupported layout')
    h=bytearray(data[:HEADER]);struct.pack_into('<I',h,48,0)
    if zlib.crc32(h)!=v[10] or zlib.crc32(data[HEADER:DATA])!=v[9]:raise ValueError('metadata CRC mismatch')
    if not DATA<=v[6]<=CAPACITY or v[6]%2048 or any(v[11:]):raise ValueError('bad used size')
    entries=[];spans=[]
    for i in range(SLOTS):
        a=struct.unpack_from('<16I',data,HEADER+i*ENTRY)
        if a[0]!=i or a[1] not in (0,1):raise ValueError('bad slot')
        if not a[1]:continue
        _,_,off,n,rate,ch,frames,start,end,gain,crc,*reserved=a
        if off%2048 or off<DATA or not 0<n<=MAX_TRACK or off+n>v[6] or rate!=48000 or ch!=2 or not (frames>0 and (start==0 and end==frames if v[0]==1 else 0<=start<end<=frames)) or gain>(0x7fff if v[0]==1 else 260904) or (any(reserved) if v[0]==1 else (reserved[0] not in (0,1) or any(reserved[1:]))):raise ValueError('bad entry')
        if any(max(off,x)<min(off+n,y) for x,y in spans):raise ValueError('overlapping tracks')
        spans.append((off,off+n))
        if len(data)>=off+n and zlib.crc32(data[off:off+n])!=crc:raise ValueError('track CRC mismatch')
        entries.append(a)
    return entries

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('ogg',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    q=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(a.ogg)]))['streams'][0]
    if q['codec_name']!='vorbis' or q['sample_rate']!='48000' or q['channels']!=2 or q['time_base']!='1/48000':raise ValueError('48 kHz stereo Vorbis required')
    prefix=build_prefix(a.ogg.read_bytes(),int(q['duration_ts']));validate_prefix(prefix)
    with a.output.open('wb') as f:f.write(prefix);f.truncate(CAPACITY)
    print(json.dumps(dict(used=len(prefix),capacity=CAPACITY,tracks=1,frames=q['duration_ts'])))

def build_tracks(tracks):
    """V2: multiple tracks, sample-accurate loop range, once flag, Q16 PCM gain."""
    table=bytearray(SLOTS*ENTRY)
    for i in range(SLOTS):struct.pack_into('<I',table,i*ENTRY,i)
    payload=bytearray();used=DATA
    for ident,t in sorted(tracks.items()):
        if not isinstance(ident,int) or not 0<=ident<101:raise ValueError('unknown BGM ID')
        ogg=t['ogg'];frames=t['frames'];start=t.get('start',0);end=t.get('end',frames);gain=t.get('gain',65536);once=int(t.get('once',False))
        if not ogg.startswith(b'OggS') or not 0<len(ogg)<=MAX_TRACK:raise ValueError('invalid Vorbis data')
        if not 0<frames<2**32 or not 0<=start<end<=frames or not 0<=gain<=260904:raise ValueError('invalid track settings')
        struct.pack_into('<16I',table,HEADER*0+ident*ENTRY,ident,1,used,len(ogg),48000,2,frames,start,end,gain,zlib.crc32(ogg),once,0,0,0,0)
        payload.extend(ogg);pad=(-len(ogg))%2048;payload.extend(bytes(pad));used+=len(ogg)+pad
    if used>CAPACITY:raise ValueError('container is full')
    h=bytearray(HEADER);h[:8]=MAGIC;struct.pack_into('<14I',h,8,2,HEADER,HEADER,ENTRY,SLOTS,DATA,used,CAPACITY,0x53500002,zlib.crc32(table),0,0,0,0);struct.pack_into('<I',h,48,zlib.crc32(h))
    result=bytes(h+table+payload);validate_prefix(result);return result
