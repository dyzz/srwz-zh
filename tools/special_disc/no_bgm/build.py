"""Isolated SP Battle Viewer no-BGM choice, retaining native speech and effects."""
from pathlib import Path
import argparse,struct,subprocess,sys,json,hashlib,shutil
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'tools'))
from srwz.iso9660 import member_map,scan_iso9660
from special_disc.iso_relocation import append_members,verify_relocation,verify_untouched
from special_disc.no_bgm.apply import apply_no_bgm

def main():
 p=argparse.ArgumentParser();p.add_argument('--source',type=Path,default=R/'build/iso/special-disc/sp-current.iso');p.add_argument('--output',type=Path,default=R/'build/iso/test/sp-no-bgm.iso');p.add_argument('--workdir',type=Path,default=R/'work/analysis/sp-no-bgm-20261105/build');p.add_argument('--replace',action='store_true');a=p.parse_args();src=a.source.resolve();dst=a.output.resolve();w=a.workdir.resolve();w.mkdir(parents=True,exist_ok=True)
 if dst.parent!=R/'build/iso/test' or dst==src:raise ValueError('test output only')
 if dst.exists() and not a.replace:raise FileExistsError(dst)
 ms=member_map(scan_iso9660(src));m=ms['SLPS_259.20']
 with src.open('rb') as f:f.seek(m.extent_lba*2048);b=bytearray(f.read(m.size))
 b,details=apply_no_bgm(bytes(b),workdir=w)
 if dst.exists():dst.unlink()
 subprocess.run(['cp','-c',str(src),str(dst)],check=True)
 rec=append_members(dst,ms,{'SLPS_259.20':bytes(b)},catalog_policy='inherit');verify=verify_relocation(dst,ms,{'SLPS_259.20':bytes(b)},rec);untouched=verify_untouched(src,dst,rec['touched_spans'])
 out=dict(source=str(src),iso=str(dst),**details,relocation=rec,readback=verify,untouched=untouched)
 (w/'receipt.json').write_text(json.dumps(out,indent=2)+'\n');(w/'patched.elf').write_bytes(b);print(dst)
if __name__=='__main__':main()
