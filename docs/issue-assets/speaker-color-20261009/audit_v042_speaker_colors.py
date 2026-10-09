"""Audit frozen v0.4.2 raw STAGE speaker recognition; no ISO writes.

Usage: python3 <script> <localized-iso> [<japanese-source-iso>]
Paths are relative to srwz-zh. BEST uses its native base and stable IDs.
The actual executable constant selects the target recognizer. Frozen font
assignments and authoring corpus are read from release commit 25f302e.
The result is a static model of 0x220E70/0x221030, not runtime validation.
"""
import collections
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'config/story-component.json').is_file())
sys.path.insert(0, str(ROOT))
from tools.srwz.codec import decode_production
from tools.srwz.iso9660 import scan_iso9660, member_map
from tools.srwz.iso_layout import ExecutableOffsetSpec, read_executable_archive_offsets
from tools.srwz.stage import parse_stage
from tools.srwz.story_quotes import logical_outer_text
from tools.srwz.text import load_text_table, project_runtime_text_table, original_fullwidth_ascii_overrides

def member(iso, name):
    entry = member_map(scan_iso9660(iso))[name]
    with iso.open('rb') as f:
        f.seek(entry.extent_lba * 2048)
        return f.read(entry.size)

def recognizer(raw, quotes):
    # 0x221030(text, 1) selects the second raw newline-separated line and
    # returns false if it is empty. 0x220E70 compares its first two bytes.
    lines = raw.split(b'\x0a')
    return len(lines) > 1 and bool(lines[1]) and lines[1][:2] in quotes

def git_json(path):
    return json.loads(subprocess.check_output(['git', 'show', '25f302e:' + path], cwd=ROOT))

table = load_text_table(ROOT / 'vendor/upstream-python/project/tbl_all.json')
assignments = git_json('config/encoding/zh-release-font-assignments.json')
overrides = {e['character']: int(e['code'], 16) for e in assignments['primary_assignments']}
overrides.update({e['character']: int(e['code'], 16) for e in assignments['surface_alias_assignments']})
overrides.update(original_fullwidth_ascii_overrides(table))
zh_table = project_runtime_text_table(table, overrides)
iso = ROOT / sys.argv[1]
jp_iso = ROOT / (sys.argv[2] if len(sys.argv) > 2 else 'rom/original.iso')
slps_name = 'SLPS_732.70' if 'best' in iso.name else 'SLPS_258.87'
exe = member(iso, slps_name)
blocks = [bytes.fromhex(s) for s in ('91410000000000008169000000000000', '91410000000000008fe8000000000000')]
matches = [b for b in blocks if exe.count(b)]
assert len(matches) == 1 and exe.count(matches[0]) == 1
quote_block = matches[0]
quote_offset = exe.index(quote_block)
spec = ExecutableOffsetSpec('STAGE', 'HEDBDY/HB.BIN', 30320, 31144)
archives = [member(p, 'DATA/STAGE.BIN') for p in (jp_iso, iso)]
offsets = [read_executable_archive_offsets(member(p, 'HEDBDY/HB.BIN'), spec, len(a)) for p, a in zip((jp_iso, iso), archives)]
paths = subprocess.check_output(['git','ls-tree','-r','--name-only','25f302e','corpus/zh/story-dialogue'], cwd=ROOT, text=True).splitlines()
translations = {}
for path in paths:
    translations.update({e['id']: e['translation'] for e in git_json(path)['entries']})
counts = collections.Counter()
lost = []
not_recognized = []
for stage in sorted({int(e.split('/')[1]) for e in translations}):
    parsed = []
    decoded = []
    for a, o, t in zip(archives, offsets, (table, zh_table)):
        block = decode_production(a[o[stage]:o[stage+1]]).output
        decoded.append(block)
        parsed.append(parse_stage(block, t, stage_index=stage, base_address=0x756ef0 if slps_name == 'SLPS_732.70' else 0x7566f0))
    entries = [{e.entry_id: e for e in p.entries if e.kind == 'dialogue'} for p in parsed]
    assert entries[0].keys() == entries[1].keys()
    speakers = [{e.speaker_id: e.text for e in p.entries if e.kind == 'speaker'} for p in parsed]
    for key, source in entries[0].items():
        target = entries[1][key]
        raw = [b[e.text_offset:b.index(b'\0', e.text_offset)] for b,e in zip(decoded,(source,target))]
        jp = recognizer(raw[0], (b'\x81\x75', b'\x81\x69'))
        zh = recognizer(raw[1], (quote_block[:2], quote_block[8:10]))
        counts[f'jp_{int(jp)}_zh_{int(zh)}'] += 1
        counts['dialogue'] += 1
        row = dict(id=key, source_speaker=speakers[0][source.speaker_id], speaker=speakers[1][target.speaker_id], source_text=source.text, text=target.text, source_hex=raw[0].hex(), hex=raw[1].hex())
        if jp and not zh:
            lost.append(row)
        if not zh and row['speaker'].strip(' 　'):
            not_recognized.append(row)
        if slps_name == 'SLPS_258.87' and logical_outer_text(target.text).replace('　',' ') != logical_outer_text(translations[key]).replace('　',' '):
            counts['frozen_translation_visible_text_mismatch'] += 1
    print('stage', stage, 'done', flush=True) if stage % 25 == 0 else None
h = hashlib.sha256()
with iso.open('rb') as f:
    for chunk in iter(lambda: f.read(4*1024*1024), b''):
        h.update(chunk)
report = dict(iso=str(iso), iso_sha256=h.hexdigest(), executable_sha256=hashlib.sha256(exe).hexdigest(), quote_file_offset=hex(quote_offset), quote_block_hex=exe[quote_offset:quote_offset+16].hex(), counts=dict(counts), lost=lost, named_unrecognized=not_recognized, evidence='static raw-byte model of shared recognizer; not runtime or visual validation')
out = ROOT / 'work' / (iso.stem + '-speaker-audit.json')
out.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k not in ('lost','named_unrecognized')}, ensure_ascii=False))
print('lost',len(lost),'named_unrecognized',len(not_recognized),'report',out)
print(json.dumps(lost[:8],ensure_ascii=False,indent=2))
