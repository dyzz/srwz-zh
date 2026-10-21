"""Verify current bounded compact-digit fix, archived runtime and source bindings."""
from pathlib import Path
import json,hashlib,struct,ast,sys,re
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'tools'));E=Path(__file__).parent
from srwz.iso9660 import member_map,scan_iso9660
from srwz.library_optical_metrics import regions
from srwz.library_body_metrics import EDITIONS
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def load(p):return json.loads(p.read_text())
def filehash(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
for row in load(E/'source-bindings.json')['files']:
 p=R/row['path'];assert p.stat().st_size==row['size'] and sha(p)==row['sha256'],row['path']
proof=load(E/'automatic-digit-production-proof.json');assert proof['case_count']==15360 and proof['source_sha256']==sha(R/'tools/srwz/compact_digit_metrics.py')
assert all(r['persistent_state_unchanged'] and r['uploads_unchanged'] for r in proof['cases'])
batch=load(E/'production-build.json');ledger=load(E/'native-patch-ledger.json');versions=[]
for result in batch['results']:
 ed=result['edition_id'];iso=R/result['output']['path'];assert filehash(iso)==result['output']['sha256'];cfg=load(R/f'config/editions/{ed}/edition.json');name=cfg['executable']['member'];m=member_map(scan_iso9660(iso))[name]
 with iso.open('rb') as f:f.seek(m.extent_lba*2048);elf=f.read(m.size)
 assert hashlib.sha256(elf).hexdigest()==ledger[ed]['compiled_elf_sha256']
 assert len(ledger[ed]['writes'])==10
 for row in ledger[ed]['writes']:
  at=int(row['file_offset'],16);assert elf[at:at+row['size']]==bytes.fromhex(row['after_hex']) and row['live_EE_matches_ISO']
 for va,before,after in regions(ed):
  row=next(x for x in ledger[ed]['writes'] if int(x['va'],16)==va);assert row['before_hex']==before.hex() and row['after_hex']==after.hex()
 receipt=load(E/'flow'/ed/'receipt.json');assert receipt['iso_sha256']==result['output']['sha256'];assert all(not x['command'].startswith(('poke ','state ')) for x in receipt['commands'])
 versions.append(dict(edition=ed,iso=result['output'],patch_regions=10,live_loaded_code_matches=True))
old=(E/'flow/sp/records-before.txt').read_text();raw=bytes.fromhex(ast.literal_eval(old[old.index('['):])[0]);new=(E/'flow/sp/glyph-records.bin').read_bytes()
assert [struct.unpack_from('<2h',raw,i*32+12) for i in (91,92,93)]==[(14,10)]*3
assert [struct.unpack_from('<2h',new,i*32+12) for i in (91,92,93)]==[(14,9)]*3
for i in (90,94,95):assert struct.unpack_from('<2h',new,i*32+12)==struct.unpack_from('<2h',raw,i*32+12)==(16,10)
loaded=load(E/'loaded-text-proof.json');sp=next(x for x in loaded['cases'] if x['edition']=='sp');assert hashlib.sha256(bytes.fromhex(load(E/'diagnostic-probe.json')['original_payload'])).hexdigest()==sp['payload_sha256']
characters=[]
for ed in EDITIONS:
 for name in ('lily-top.png','lily-scroll.png','alex-top.png','alex-scroll.png'):
  current=E/'characters'/ed/name;prior=R/'docs/issue-assets/control-layout-audit-20261021/final'/ed/name;assert current.read_bytes()==prior.read_bytes();characters.append(dict(edition=ed,image=name,sha256=sha(current),same_as_previously_accepted=True))
for n in (2,6,90,93,110):assert (E/f'story/current/story-dialogue-{n:03}.png').read_bytes()==(E/f'story/baseline/story-dialogue-{n:03}.png').read_bytes()
story=load(E/'story/runtime-scope.json');assert not story['source_writes'] and not story['save_state_restore'] and not story['story_013_natural_event_reached']
state=(E/'story/current-font-state.bin').read_bytes();assert struct.unpack_from('<4h',state,0x14)==(22,11,22,11);assert struct.unpack_from('<8h',state,0x38)==(22,11,22,11,22,11,22,11)
t=(E/'tests-full.log').read_text();assert 'Ran 843 tests' in t and 'OK (skipped=1)' in t
t=(E/'tests-indexed-full-final.log').read_text();assert 'Ran 811 tests' in t and 'OK (skipped=8)' in t
t=(E/'tests-indexed-sp-assets.log').read_text();assert 'Ran 37 tests' in t and '\nOK' in t
links=[]
for name in ('COMPACT_DIGIT_HEIGHT_AND_STORY_AUDIT_20261021.md','TEXT_CONTROL_AND_LAYOUT_HANDOFF_20261021.md','TEXT_CONTROL_LAYOUT_AUDIT_20261021.md'):
 p=R/'docs'/name
 for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
  if '://' in target or target.startswith('#'):continue
  q=(p.parent/target.split('#')[0]).resolve();assert q.exists() or q==E/'receipt.json',(name,target);links.append(target)
files=[p for p in sorted(E.rglob('*')) if p.is_file() and p.name!='receipt.json' and '__pycache__' not in p.parts]
out=dict(status='passed_bounded_native_compact_digits_three_ISOs_flow_and_character_regression',full_reverse_engineering_complete=False,source_files=len(load(E/'source-bindings.json')['files']),native_differential_cases=15360,tests=dict(worktree=dict(total=843,passed=842,skipped=1),indexed_full=dict(total=811,passed=803,skipped=8,local_SP_ISO_unavailable_in_that_export=True),indexed_SP_asset_supplement=dict(total=37,passed=37,skipped=0)),editions=versions,flow_digit_geometry_before=[14,10],flow_digit_geometry_after=[14,9],flow_Chinese_geometry_unchanged=[16,10],SP_synopsis_text_bytes_unchanged=True,character_runtime=characters,story_scope=story,story_post_frame_explicit_metrics=[22,11,22,11],story_post_frame_state_limit='May be overwritten by later fields; not a body line-spacing observation',local_links_checked=len(links),files=[dict(path=str(p.relative_to(R)),size=p.stat().st_size,sha256=sha(p)) for p in files])
(E/'receipt.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');print('PASS: 15360 native cases, three ISO and EE code ledgers, unchanged synopsis bytes, 10->9 digits, 12 identical character pages, bounded natural story samples, indexed suite and SP supplement')
