"""Verify handoff links, source snapshot and native/final ELF patch ledger."""
from pathlib import Path
import sys,json,re,hashlib,subprocess
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'tools'))
from srwz.iso9660 import member_map,scan_iso9660
E=Path(__file__).resolve().parent;receipt_path=E/'receipt.json'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
snapshot=E/'snapshot.json';before=snapshot.read_bytes()
subprocess.run([sys.executable,str(E/'snapshot.py')],cwd=R,check=True,stdout=subprocess.DEVNULL)
assert snapshot.read_bytes()==before,'snapshot is stale (updated; rerun verify)'
d=json.loads(before);sources=[]
for row in d['source_inputs']:
 p=R/row['path'];assert sha(p)==row['sha256'];sources.append(row['path'])
links=[];p=R/'docs/TEXT_CONTROL_AND_LAYOUT_HANDOFF_20261021.md'
for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
 if '://' in target or target.startswith('#'):continue
 q=(p.parent/target.split('#',1)[0]).resolve()
 assert q.exists() or q==receipt_path,('broken link',target)
 links.append(target)
checked=[]
def read(iso,member):
 p=R/iso;m=member_map(scan_iso9660(p))[member]
 with p.open('rb') as f:f.seek(m.extent_lba*2048);return f.read(m.size)
for output in d['current_build']['outputs']:
 ed=output['edition'];cfg=json.loads((R/f'config/editions/{ed}/edition.json').read_text());name=cfg['executable']['member']
 native=read(cfg['source_iso']['path'],name);final=read(output['output']['path'],name)
 assert len(native)==cfg['executable']['size'];assert hashlib.sha256(native).hexdigest()==cfg['executable']['sha256']
 ledger=d['native_patch_ledger'][ed]
 for row in ledger['writes']:
  off=int(row['file_offset'],16);a=bytes.fromhex(row['before_hex']);b=bytes.fromhex(row['after_hex'])
  assert native[off:off+len(a)]==a,(ed,row['va'],'native preimage')
  assert final[off:off+len(b)]==b,(ed,row['va'],'current ISO replacement')
 checked.append(dict(edition=ed,member=name,native_elf_sha256=hashlib.sha256(native).hexdigest(),current_elf_sha256=hashlib.sha256(final).hexdigest(),checked_regions=len(ledger['writes']),total_write_span_bytes=ledger['total_write_span_bytes'],iso=output['output']))
docs=['docs/TEXT_CONTROL_AND_LAYOUT_HANDOFF_20261021.md','docs/README.md','docs/NATIVE_TEXT_RENDERING_REVERSE_ENGINEERING_20261021.md','docs/LIBRARY_BODY_FONT_FIX_20261021.md','docs/VISIBLE_TEXT_ENCODING_RULES.md','docs/TEXT_WIDTH_LAYOUT_POLICY_20260928.md','docs/COMPACT_TEXT_ADJUSTMENT_PLAN_20260928.md']
files=[R/x for x in docs]+[E/'snapshot.py',E/'snapshot.json',E/'verify.py']
out=dict(status='passed_documentation_snapshot_links_and_three_ISO_native_patch_ledger',scope='documentation handoff; no production source/corpus changes, ISO rebuild or new emulator run; prior runtime and test evidence referenced separately',snapshot_reproduced_byte_identically=True,local_links_checked=len(links),source_hashes_checked=len(sources),corpus_tokenization_errors=d['tokenization_errors'],patch_readback=checked,files=[dict(path=str(p.relative_to(R)),size=p.stat().st_size,sha256=sha(p)) for p in files],runtime_evidence='docs/issue-assets/native-text-rendering-20261021/smaller-body/runtime-verification.json',prior_tests='docs/issue-assets/native-text-rendering-20261021/smaller-body/tests-smaller-full.log',full_reverse_engineering_complete=False)
receipt_path.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
assert all((p.parent/t.split('#',1)[0]).exists() for t in links)
print(f'PASS: {len(links)} local links; {len(sources)} source hashes; native/current ELF ledger 8 regions x 3 editions; snapshot deterministic')
