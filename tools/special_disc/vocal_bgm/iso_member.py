"""Add the reserved music member to the SP ISO9660/UDF bridge and VMAP.

Narrow profile: existing BGM directory has sector slack, VMAP has an unused
allocated tail, one UDF partition and short allocation descriptors. Fail closed
on layout drift. Existing file extents are never relocated here.
"""
from pathlib import Path
import math,struct
from srwz.iso9660 import scan_iso9660,member_map
from special_disc.event_gallery.udf import Disc,u16,u32,crc_tag,validate_tag
B=2048
class DetailDisc(Disc):
    def __init__(self,f):self.dirs={};super().__init__(f)
    def walk(self,icb,path,visited):
        fe=self.read(self.partition_start+icb)
        if fe[27]==4:
            ad=176+u32(fe,168)
            self.dirs[path.upper()]=dict(fe_lba=self.partition_start+icb,fe=fe,ad_offset=ad,extent_lba=self.partition_start+u32(fe,ad+4),size=u32(fe,ad))
        super().walk(icb,path,visited)
def directory_records(data):
    pos=0
    while pos<len(data):
        n=data[pos]
        if not n:pos=(pos//B+1)*B;continue
        if n<34 or pos+n>len(data):raise ValueError('bad ISO directory')
        yield pos,data[pos:pos+n]
        pos+=n

def add_music(image:Path,prefix:bytes,capacity:int):
    before=member_map(scan_iso9660(image));im=scan_iso9660(image)
    if 'BGM/VOCAL.BIN' in before:raise ValueError('music member already exists')
    if capacity% B or len(prefix)>capacity or capacity>=1<<30:raise ValueError('bad capacity')
    old_size=image.stat().st_size;music_lba=old_size//B;fe_lba=music_lba+capacity//B
    tail=fe_lba+1;final_anchor=tail+256;total=final_anchor+1
    writes={};spans=[]
    def write_at(at,data):writes[at]=bytes(data);spans.append((at,at+len(data)))
    with image.open('r+b') as f:
        disc=DetailDisc(f)
        f.seek(im.root_directory_extent_lba*B);root=f.read(im.root_directory_size)
        root_pos,bgm_dir=next((p,q) for p,q in directory_records(root) if q[33:33+q[32]]==b'BGM')
        iso_dir_lba,iso_dir_size=u32(bgm_dir,2),u32(bgm_dir,10)
        if iso_dir_size>B:raise ValueError('BGM ISO directory no longer fits one sector')
        f.seek(iso_dir_lba*B);directory=bytearray(f.read(B));records=list(directory_records(directory[:iso_dir_size]));last=records[-1][0]+len(records[-1][1])
        template=next(q for _,q in records if q[33:33+q[32]]==b'BGM.BIN;1')
        name=b'VOCAL.BIN;1';rec=bytearray(template[:33]+name);rec+=bytes(len(rec)%2);rec[0]=len(rec);rec[32]=len(name)
        struct.pack_into('<I',rec,2,music_lba);struct.pack_into('>I',rec,6,music_lba);struct.pack_into('<I',rec,10,capacity);struct.pack_into('>I',rec,14,capacity)
        end=last+len(rec)
        if end>B or any(directory[last:end]):raise ValueError('BGM ISO directory slack not empty')
        directory[last:end]=rec
        new_size=max(iso_dir_size,end)
        struct.pack_into('<I',directory,10,new_size);struct.pack_into('>I',directory,14,new_size)
        write_at(iso_dir_lba*B,directory)
        write_at(im.root_directory_extent_lba*B+root_pos+10,struct.pack('<I',new_size)+struct.pack('>I',new_size))
        # Append a native catalog row and keep a terminating zero row.
        v=before['VMAP.DAT'];f.seek(v.extent_lba*B);catalog=bytearray(f.read(math.ceil(v.size/B)*B))
        used=next(i for i in range(0,v.size,48) if catalog[i:i+48]==bytes(48));new_vmap_size=max(v.size,used+96)
        if new_vmap_size>len(catalog) or any(catalog[used:new_vmap_size]):raise ValueError('VMAP has no zero allocated slack')
        srcrow=next(catalog[i:i+48] for i in range(0,used,48) if b'BGM.BIN;1' in catalog[i:i+40])
        path=srcrow[:40].split(b'\0')[0].replace(b'BGM.BIN;1',b'VOCAL.BIN;1')
        row=path.ljust(40,b'\0')+struct.pack('<II',music_lba,capacity//B);catalog[used:used+48]=row
        write_at(v.extent_lba*B,catalog[:new_vmap_size]);write_at(v.directory_record_offset+10,struct.pack('<I',new_vmap_size)+struct.pack('>I',new_vmap_size))
        # New UDF file identifier in existing BGM directory allocation.
        dr=disc.dirs['BGM'];f.seek(dr['extent_lba']*B);ud=bytearray(f.read(B));pos=0;fid_template=None
        while pos<dr['size']:
            n=(38+u16(ud,pos+36)+ud[pos+19]+3)&~3
            validate_tag(ud[pos:pos+n],257)
            if not ud[pos+18]&12:fid_template=ud[pos:pos+n]
            pos+=n
        if pos!=dr['size'] or fid_template is None:raise ValueError('unexpected UDF BGM directory')
        encoded=b'\x08VOCAL.BIN';fid=bytearray(fid_template[:38]);fid[18]=0;fid[19]=len(encoded);struct.pack_into('<H',fid,36,0);fid+=encoded;fid+=bytes((-len(fid))%4)
        struct.pack_into('<I',fid,20,B);struct.pack_into('<I',fid,24,fe_lba-disc.partition_start);struct.pack_into('<H',fid,10,len(fid)-16);fid=crc_tag(fid,dr['extent_lba']-disc.partition_start)
        if pos+len(fid)>B or any(ud[pos:pos+len(fid)]):raise ValueError('no UDF directory slack')
        ud[pos:pos+len(fid)]=fid;write_at(dr['extent_lba']*B,ud)
        def resized(record,size,lba=None):
            fe=bytearray(record['fe']);struct.pack_into('<Q',fe,56,size);struct.pack_into('<Q',fe,64,math.ceil(size/B));struct.pack_into('<I',fe,record['ad_offset'],size)
            if lba is not None:struct.pack_into('<I',fe,record['ad_offset']+4,lba-disc.partition_start)
            return fe
        write_at(dr['fe_lba']*B,crc_tag(resized(dr,pos+len(fid))))
        vr=disc.files['VMAP.DAT'];write_at(vr['fe_lba']*B,crc_tag(resized(vr,new_vmap_size)))
        fr=disc.files['BGM/BGM.BIN'];newfe=resized(fr,capacity,music_lba)
        uid=max(struct.unpack_from('<Q',x['fe'],160)[0] for x in [*disc.files.values(),*disc.dirs.values()])+1
        struct.pack_into('<Q',newfe,160,uid);write_at(fe_lba*B,crc_tag(newfe,fe_lba-disc.partition_start))
        partition_length=final_anchor-disc.partition_start
        for sequence in disc.sequences:
            for lba,kind,data in sequence:
                if kind==5:
                    b=bytearray(data);struct.pack_into('<I',b,192,partition_length);write_at(lba*B,crc_tag(b))
        integrity=bytearray(disc.integrity);struct.pack_into('<I',integrity,84,partition_length);struct.pack_into('<I',integrity,120,u32(integrity,120)+1);write_at(disc.integrity_lba*B,crc_tag(integrity))
        for lba in [tail,final_anchor]:write_at(lba*B,crc_tag(disc.anchor,lba))
        for lba in range(16,32):
            f.seek(lba*B);data=bytearray(f.read(B))
            if data[1:6]==b'CD001' and data[0] in (1,2):struct.pack_into('<I',data,80,total);struct.pack_into('>I',data,84,total);write_at(lba*B,data)
        f.truncate(total*B);f.seek(music_lba*B);f.write(prefix)
        for at,data in sorted(writes.items()):f.seek(at);f.write(data)
        f.flush();after_udf=DetailDisc(f)
        assert after_udf.files['BGM/VOCAL.BIN']['extent_lba']==music_lba
        for name,x in disc.files.items():
            y=after_udf.files[name];assert x['extent_lba']==y['extent_lba'];assert y['size']==(new_vmap_size if name=='VMAP.DAT' else x['size'])
    after=member_map(scan_iso9660(image));assert after['BGM/VOCAL.BIN'].extent_lba==music_lba and after['BGM/VOCAL.BIN'].size==capacity
    for name,x in before.items():
        y=after[name];assert x.extent_lba==y.extent_lba and y.size==(new_vmap_size if name=='VMAP.DAT' else x.size)
    return dict(path='BGM/VOCAL.BIN',lba=music_lba,capacity=capacity,used=len(prefix),vmap_size=new_vmap_size,metadata_spans=spans,new_size=total*B,previous_size=old_size,fe_lba=fe_lba)
