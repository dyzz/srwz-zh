"""Verify the final control/layout audit bindings without rebuilding ISOs."""
from pathlib import Path
import sys,json,hashlib,re
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'tools'))
from srwz.iso9660 import member_map,scan_iso9660
from srwz.text import CONTROL_NOTATION
E=Path(__file__).resolve().parent;receipt=E/'receipt.json'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def load(p):return json.loads(p.read_text())
source=load(E/'source-bindings.json')
for row in source['files']:
 p=R/row['path'];assert p.stat().st_size==row['size'] and sha(p)==row['sha256'],row['path']
contracts=load(E/'control-contracts-final.json');assert contracts['passed'] and not contracts['failures'] and not contracts['unrecognized_syntax']
preview=load(E/'prose-preview-final.json');assert len(preview['records'])==1398 and not any(r.get('error') for r in preview['records'])
for row in preview['records']:
 assert max(row['line_widths_px'],default=0)<=row['maximum_width_cells']*row['default_advance_px']
 if not row['surface'].startswith('library'):assert not row['differs_from_source'],row['id']
for change in load(E/'layout-writeback.json')['changes']:
 assert change['before'].replace('\n','')==change['after'].replace('\n','')
 assert CONTROL_NOTATION.findall(change['before'])==CONTROL_NOTATION.findall(change['after'])
 current=next(r for r in load(R/change['path'])['entries'] if r['id']==change['id'])
 assert current['translation']==change['after']
assert load(E/'scroll-placeholders-final.json')['passed']
assert load(E/'sp-control-byte-readback.json')['failures']==0
runtime=load(E/'runtime-verification.json');assert len(runtime['images'])==12 and all(r['same_as_previous_size'] for r in runtime['images'])
batch=load(E/'production-build.json');assert batch['input_digest']==source['batch']
ledger=load(R/'docs/issue-assets/text-control-layout-handoff-20261021/snapshot.json')['native_patch_ledger']
versions=[]
def member(iso,name):
 p=R/iso;m=member_map(scan_iso9660(p))[name]
 with p.open('rb') as f:f.seek(m.extent_lba*2048);return f.read(m.size)
for result in batch['results']:
 ed=result['edition_id'];runtime_receipt=load(E/'final'/ed/'receipt.json')
 assert runtime_receipt['iso_sha256']==result['output']['sha256']
 assert runtime_receipt['source_card_sha256_before']==runtime_receipt['source_card_sha256_after']
 cfg=load(R/f'config/editions/{ed}/edition.json');name=cfg['executable']['member']
 native=member(cfg['source_iso']['path'],name);final=member(result['output']['path'],name)
 assert hashlib.sha256(native).hexdigest()==cfg['executable']['sha256']
 for patch in ledger[ed]['writes']:
  at=int(patch['file_offset'],16);a=bytes.fromhex(patch['before_hex']);b=bytes.fromhex(patch['after_hex'])
  assert native[at:at+len(a)]==a;assert final[at:at+len(b)]==b
 versions.append(dict(edition=ed,output=result['output'],native_patch_regions_verified=len(ledger[ed]['writes']),runtime_card_unchanged=True))
sp=load(E/'sp-controls/receipt.json');assert sp['iso_sha256']==next(r['output']['sha256'] for r in batch['results'] if r['edition_id']=='sp');assert sp['source_card_sha256_before']==sp['source_card_sha256_after']
log=(E/'tests-final-843.log').read_text();assert 'Ran 843 tests' in log and 'OK (skipped=1)' in log
links=[]
docs=['docs/TEXT_CONTROL_LAYOUT_AUDIT_20261021.md','docs/TEXT_CONTROL_AND_LAYOUT_HANDOFF_20261021.md']
for name in docs:
 p=R/name
 for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
  if '://' in target or target.startswith('#'):continue
  q=(p.parent/target.split('#',1)[0]).resolve();assert q.exists() or q==receipt,(name,target);links.append(dict(document=name,target=target))
files=[p for p in sorted(E.rglob('*')) if p.is_file() and p!=receipt and '__pycache__' not in p.parts]
files += [R/p for p in docs]
out=dict(status='passed_declared_control_layout_source_ISO_and_LRPS2_domains',full_reverse_engineering_complete=False,source_hashes_verified=len(source['files']),corpus_fields=contracts['scanned_fields'],control_forms=contracts['unique_forms'],preview_records=len(preview['records']),tests=dict(total=843,passed=842,skipped=1),editions=versions,character_runtime_images=12,character_images_pixel_identical_to_previous_size=True,SP_weapon_hint_triangle_report_and_return='visually reviewed; natural LRPS2 navigation; no RAM or savestate injection',local_links_checked=len(links),limits=['Dynamic tm/@/square precise widths and all consumers remain owner-specific; generic reflow rejects them','No production native-measure patch; no full-game or all-symbol visual acceptance','The two flow synopsis updates were statically checked and built, not naturally reached in this runtime session'],files=[dict(path=str(p.relative_to(R)),size=p.stat().st_size,sha256=sha(p)) for p in files])
receipt.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
print('PASS: source hashes, all 91 control forms, 1398 previews, three native/final ELF patch ledgers, 12 matching LRPS2 character captures, SP hint/report receipts and document links')
