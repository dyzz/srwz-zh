"""Read actual edition ISOs; verify shared I bytes and unchanged indexed donor."""
from pathlib import Path
import argparse,json,hashlib,sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tools'))
from srwz.iso9660 import scan_iso9660,member_map
from srwz.tim2 import parse_tim2
from srwz.file_identity import sha256_file

def sha(raw):return hashlib.sha256(raw).hexdigest()
def read(path):
    mm=member_map(scan_iso9660(path));out={}
    with path.open('rb') as f:
        for name in ['KURODATA/KVPDATA.BIN','KURODATA/KVMDATA.BIN']:
            m=mm[name];f.seek(m.extent_lba*2048);out[name]=f.read(m.size)
    return out,mm

def verify(root,before=None):
    headings=json.loads((root/'config/assets/ui-headings-zh.json').read_text())
    sp=json.loads((root/'config/assets/special-disc/title-atlas.json').read_text())
    result={'status':'all_three_editions_shared_I_readback_passed','editions':{},'runtime':'pending'}
    for ed in ['original','best','sp']:
        receipt=json.loads((root/f'manifests/editions/{ed}/current.json').read_text());path=root/receipt['output']['path'];assert sha256_file(path)==receipt['output']['sha256'];raw,mm=read(path)
        kvp=raw['KURODATA/KVPDATA.BIN'];kvm=raw['KURODATA/KVMDATA.BIN']
        patches=headings['shared_letter_patches'] if ed!='sp' else [p for p in sp['patches'] if p['token']=='pilot-i']
        refs=[]
        for patch in patches:
            off=patch['offset'];after=bytes.fromhex(patch['after_hex']);assert kvp[off:off+22]==after,(ed,off)
            assert kvp[off+18:off+22]==bytes([14,16,19,32])
            refs.append({'offset':off,'raw_hex':after.hex(),'uv':[14,16,19,32]})
        chunk=next(c for c in headings['texture_chunks'] if c['index']==2)
        rec=parse_tim2(kvm,offset=chunk['start']);pic=rec.pictures[0]
        assert (pic.width,pic.height,pic.image_type)==(256,256,4)
        begin=pic.offset+pic.header_size;idx=bytes(v for b in kvm[begin:begin+pic.image_size] for v in (b&15,b>>4))
        donor=bytes(idx[y*256+x] for y in range(16,32) for x in range(14,19));assert sha(donor)==headings['shared_letters'][0]['indices_sha256']
        restored=b''.join(b'\0'+donor[y*5:(y+1)*5] for y in range(16));assert sha(restored)==headings['shared_letters'][0]['original_indices_sha256']
        native=root/json.loads((root/f'config/editions/{ed}/edition.json').read_text())['source_iso']['path'];native_mm=member_map(scan_iso9660(native))
        assert {n:m.extent_lba for n,m in mm.items()}=={n:m.extent_lba for n,m in native_mm.items()}
        row={'iso':receipt['output']['path'],'iso_sha256':receipt['output']['sha256'],'member_sha256':sha(kvp),'atlas_sha256':sha(kvm),'donor_indices_sha256':sha(donor),'restored_I_indices_sha256':sha(restored),'references':refs,'member_lbas_preserved':True}
        if before:
            old_path=before/f'{ed}.iso';old,old_mm=read(old_path);old_kvp=old['KURODATA/KVPDATA.BIN']
            expected=bytearray(old_kvp)
            for patch in patches:
                off=patch['offset'];assert expected[off:off+22]==bytes.fromhex(patch['before_hex']);expected[off:off+22]=bytes.fromhex(patch['after_hex'])
            assert kvp==bytes(expected),(ed,'other KVP bytes changed');assert kvm==old['KURODATA/KVMDATA.BIN'],(ed,'atlas changed')
            row.update(only_expected_KVP_records_changed=True,changed_KVP_bytes=sum(a!=b for a,b in zip(kvp,old_kvp)),atlas_byte_exact_before=True)
        result['editions'][ed]=row
    return result
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--before',type=Path);ap.add_argument('--out',type=Path,required=True);args=ap.parse_args()
    report=verify(args.root.resolve(),args.before);args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False,indent=2))
