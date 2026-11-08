"""Export exact formal-candidate executable bytes for ARMSX2 RAM comparison."""
from pathlib import Path
import argparse
import hashlib
import json
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from verify_editions import verify_batch
from srwz.iso9660 import member_map,scan_iso9660


def export(manifest,output):
 proof=verify_batch(ROOT,manifest)
 batch=json.loads(manifest.read_text())
 output.mkdir(parents=True,exist_ok=False)
 for result in batch['results']:
  edition=result['edition_id'];installed=result['typography']['verification']
  iso=ROOT/result['output']['path'];member=member_map(scan_iso9660(iso))[installed['member']]
  with iso.open('rb') as stream:
   stream.seek(member.extent_lba*2048);elf=stream.read(member.size)
  if hashlib.sha256(elf).hexdigest()!=installed['executable_sha256']:
   raise ValueError('Candidate ELF changed after verification')
  (output/f'{edition}.elf').write_bytes(elf)
  (output/f'{edition}-payload.json').write_text(json.dumps(installed['payload'],indent=2)+'\n')
  (output/f'{edition}-iso.json').write_text(json.dumps(dict(output=str(iso),isoSha256=result['output']['sha256']),indent=2)+'\n')
 (output/'batch-verification.json').write_text(json.dumps(proof,indent=2)+'\n')

if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--manifest',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
 args=parser.parse_args();export(args.manifest,args.output)
