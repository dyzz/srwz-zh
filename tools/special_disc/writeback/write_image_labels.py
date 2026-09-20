"""Write the five translated SP image labels from a locked indexed snapshot.

--refreeze explicitly authors the snapshot with the project's font. Normal
builds consume frozen pixels and preserve all CLUTs and non-target bytes.
"""
from pathlib import Path
import argparse
import base64
import json
import sys
import zlib

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'tools'),str(Path(__file__).resolve().parent)]
from write_frame_text import Writer, sd, require, stage
from srwz.codec import decode_production,reencode_changed_suffix
from srwz.world_map_titles import (unpack_vertical_linear_4bpp,pack_vertical_linear_4bpp,index_bbox,
                                    render_title_inside_bbox,replace_title_inside_bbox)
from srwz.tim2 import parse_tim2
from srwz.imagemagick import require_imagemagick
from special_disc.baselines import baseline_iso

SNAPSHOT=ROOT/'config/assets/special-disc/full-text-image-labels.json'


def render(logical,width,height,box,text,font,max_size):
    title,meta=render_title_inside_bbox(require_imagemagick(),font,text,box,width=width,height=height,
        max_point_size=max_size,min_point_size=16,kerning_candidates=(1,0.5,0),hinting=False,
        antialias=True,canvas_width=1024,canvas_height=64)
    return replace_title_inside_bbox(logical,title,box,width=width,height=height),meta


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refreeze',action='store_true')
    parser.add_argument('--output',type=Path,default=ROOT/'work/build/special-disc/full-text/image-labels')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    writer=Writer(baseline_iso('text-canary'),ROOT/'work/build/special-disc/text-candidate/font/proposal.json')
    frame={r['id']:r for r in writer.frames if r['category']=='image-label'}
    targets={t:r for r in frame.values() for t in r['locations']}
    font_lock=json.loads((ROOT/'config/fonts/harmonyos-sans-sc-light.lock.json').read_text())['font']
    font=ROOT/font_lock['path'];require(stage.sha256(font.read_bytes())==font_lock['sha256'],'image font drift')
    snapshots=[];old={} if args.refreeze else {r['key']:r for r in json.loads(SNAPSHOT.read_text())['records']}
    outputs={};reports=[]
    def frozen(key,source,logical,w,h,patches):
        identity=dict(key=key,source_sha256=stage.sha256(source),translations={t:targets[t]['translation'] for t,_ in patches})
        if args.refreeze:
            edited=logical;layout=[]
            for target,box in patches:
                edited,meta=render(edited,w,h,box,targets[target]['translation'],font,26 if w==512 else 20)
                layout.append(dict(target=target,**meta))
            record=dict(**identity,layout=layout,indexes_zlib_base64=base64.b64encode(zlib.compress(edited,9)).decode())
        else:
            record=old[key]
            require(all(record[k]==v for k,v in identity.items()),f'{key}: snapshot source/translation drift')
            edited=zlib.decompress(base64.b64decode(record['indexes_zlib_base64']))
        require(len(edited)==w*h and max(edited)<=15,'image snapshot geometry/index drift')
        for y in range(h):
            for x in range(w):
                if not any(a<=x<=c and b<=y<=d for _,(a,b,c,d) in patches):
                    require(edited[y*w+x]==logical[y*w+x],'image outside owned rect changed')
        snapshots.append(record)
        from PIL import Image
        Image.frombytes('L',(w,h),bytes(i*17 for i in edited)).save(args.output/f'{key}.png')
        return edited
    name='KURODATA/KVMDATA.BIN';base=writer.member(name);arc=bytearray(base);off=sd.table_offsets(writer.exe,0x39DF10,len(base));a,b=off[11:13];data=base[a:b];pic=parse_tim2(data).pictures[0]
    require((pic.width,pic.height,pic.image_type)==(256,256,4),'KVM label atlas format drift')
    start=pic.offset+pic.header_size;raw=data[start:start+pic.image_size]
    logical=bytes(i for byte in raw for i in (byte&15,byte>>4))
    patches=[('sd/image/kvmdata/结算提示图集/0',(144,24,255,47)),('sd/image/kvmdata/结算提示图集/1',(0,72,71,95))]
    edited=frozen('kvm11',data,logical,256,256,patches)
    packed=bytes(edited[i]|(edited[i+1]<<4) for i in range(0,len(edited),2))
    arc[a+start:a+start+len(packed)]=packed
    require(bytes(arc[a:a+start])==data[:start] and bytes(arc[a+start+len(packed):b])==data[start+len(packed):],'KVM headers/palette/trailer changed')
    outputs[name]=bytes(arc)
    for target,box in patches:reports.append(dict(target=target,member=name,chunk=11,rect=box))
    name='MAP/MAPMODEL.BIN';base=writer.member(name);arc=bytearray(base);off=sd.table_offsets(writer.exe,0x3542F0,len(base))
    for index in (195,196,197):
        a,b=off[index:index+2];stored=base[a:b];decoded=decode_production(stored);data=decoded.output
        start=0x115160;raw=data[start:start+8192];logical=unpack_vertical_linear_4bpp(raw,width=512,height=32)
        box=index_bbox(logical,width=512,height=32);target=f'sd/image/mapmodel/世界地图标题（新）/{index-195}'
        edited=frozen(f'map{index}',raw,logical,512,32,[(target,box)])
        newraw=pack_vertical_linear_4bpp(edited,width=512,height=32)
        rebuilt=data[:start]+newraw+data[start+8192:]
        require(rebuilt[:start]==data[:start] and rebuilt[start+8192:]==data[start+8192:],'map non-title bytes changed')
        packed=reencode_changed_suffix(stored,rebuilt,strategy='rust-fit',max_output_size=b-a,original_result=decoded)
        require(decode_production(packed).output==rebuilt,'map label codec readback')
        arc[a:b]=packed+bytes(b-a-len(packed));reports.append(dict(target=target,member=name,chunk=index,offset=start,allocated=b-a,compressed=len(packed),english_and_other_bytes_preserved=True))
    outputs[name]=bytes(arc)
    if args.refreeze:SNAPSHOT.write_text(json.dumps(dict(schema_version=1,font=font_lock,records=snapshots),ensure_ascii=False,indent=2)+'\n')
    report=dict(status='static_verified_runtime_pending',bindings=reports,snapshot=dict(path=str(SNAPSHOT.relative_to(ROOT)),sha256=stage.sha256(SNAPSHOT.read_bytes())),files={n:stage.sha256(d)for n,d in outputs.items()},base_files={n:stage.sha256(writer.base[n])for n in outputs},corpus_sha256=stage.sha256((ROOT/'corpus/zh/special-disc/frame-text.json').read_bytes()))
    for name,data in outputs.items():
        p=args.output/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('five image labels written; palettes, English subtitle and non-target bytes preserved')

if __name__=='__main__':main()
