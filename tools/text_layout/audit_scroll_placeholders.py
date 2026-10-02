#!/usr/bin/env python3
"""Audit native blank-row placeholders in both scrolling-text corpora."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
from srwz.codec import decode_production
from srwz.iso_layout import CORE_ARCHIVE_SPECS, read_executable_archive_offsets
from srwz.iso9660 import member_map, scan_iso9660
from srwz.summary import parse_summary, scroll_placeholder_rows, validate_scroll_placeholders
from srwz.text import load_text_table
from srwz.writeback import WritebackError


def audit(root: Path = ROOT) -> dict:
    table = load_text_table(root/'vendor/upstream-python/project/tbl_all.json')
    reference = json.loads((root/'config/full-story-components.json').read_text())['world_history']
    def locked(key):
        lock = reference[key];data = (root/lock['path']).read_bytes()
        if len(data) != lock['size'] or hashlib.sha256(data).hexdigest() != lock['sha256']:
            raise ValueError(f'native source lock drift: {key}')
        return data
    archive = locked('original');exe = locked('original_slps')
    offsets = read_executable_archive_offsets(exe, CORE_ARCHIVE_SPECS['MTV_PROS.BIN'], len(archive))
    sources = {e.entry_id:e.text for i,(a,b) in enumerate(zip(offsets,offsets[1:]))
               for e in parse_summary(decode_production(archive[a:b]).output,table,chunk_index=i).entries}
    main = json.loads((root/reference['corpus']['path']).read_text())['entries']

    sp_contract = json.loads((root/'config/editions/sp/edition.json').read_text())
    iso = root/sp_contract['source_iso']['path'];members = member_map(scan_iso9660(iso))
    with iso.open('rb') as stream:
        def member(name):
            m = members[name];stream.seek(m.extent_lba*2048);return stream.read(m.size)
        archive = member('DATA/MTZSPROS.BIN');exe = member('SLPS_259.20')
    if hashlib.sha256(exe).hexdigest() != sp_contract['executable']['sha256']:
        raise ValueError('SP native executable drift')
    offsets = []
    for i in range(5000):
        offsets.append(struct.unpack_from('<I',exe,0x387880+i*4)[0])
        if offsets[-1] == len(archive):break
    else:raise ValueError('SP native archive has no terminal offset')
    if offsets != sorted(offsets):raise ValueError('SP native archive offsets are not monotonic')
    sp_sources = {f'sd/mtzspros/{i:02d}/{j}':e.text for i,(a,b) in enumerate(zip(offsets,offsets[1:]))
                  for j,e in enumerate(parse_summary(decode_production(archive[a:b]).output,table,chunk_index=i).entries)}
    sp = [e for e in json.loads((root/'corpus/zh/special-disc/frame-text.json').read_text())['entries']
          if e.get('kind') == 'narration']
    if {t for e in sp for t in e['locations']} != set(sp_sources) or {e['id'] for e in main} != set(sources):
        raise ValueError('scroll corpus/native inventory drift')
    records = [];failures = []
    for edition,entries in (('original_and_best',main),('sp',sp)):
        for e in entries:
            source = sources[e['id']] if edition == 'original_and_best' else sp_sources[e['locations'][0]]
            if hashlib.sha256(source.encode()).hexdigest() != e['source_text_sha256']:
                raise ValueError(f'native source binding drift: {e["id"]}')
            try:validate_scroll_placeholders(source,e['translation'],label=e['id'])
            except WritebackError as error:failures.append(str(error))
            records.append(dict(edition=edition,id=e['id'],native_space_rows=list(map(len,scroll_placeholder_rows(source))),
                                translated_space_rows=list(map(len,scroll_placeholder_rows(e['translation'])))))

    paired = 0;files = 0;other_losses = []
    for path in (root/'corpus/zh').rglob('*.json'):
        doc = json.loads(path.read_text());files += 1
        if not isinstance(doc,dict):continue
        for e in doc.get('entries',[]):
            if not isinstance(e,dict) or not isinstance(e.get('source_text'),str) or not isinstance(e.get('translation'),str):continue
            paired += 1
            native = tuple(s for s in scroll_placeholder_rows(e['source_text']) if s)
            if native and tuple(map(len,native)) != tuple(map(len,scroll_placeholder_rows(e['translation']))):
                other_losses.append(dict(path=str(path.relative_to(root)),id=e.get('id'),kind=e.get('kind'),
                                         native_space_rows=list(map(len,native)),
                                         translated_space_rows=list(map(len,scroll_placeholder_rows(e['translation'])))))
    return dict(passed=not failures and not other_losses,scroll_records=records,failures=failures,
                corpus_files_scanned=files,inline_source_pairs_scanned=paired,
                other_inline_source_placeholder_changes=other_losses,
                limits='Only scrolling records are subject to this contract; fixed grids/Q&A have independent padding. '
                       'Hash-only corpus rows outside the two scrolling archives are not a native-byte audit.')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    args = parser.parse_args();result = audit()
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k != 'scroll_records'},ensure_ascii=False,indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':raise SystemExit(main())
