"""Audit SP versus Original Q&A source, current ISO and reviewed translation coverage."""
from pathlib import Path
import argparse
import difflib
import json
import struct
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/special_disc/writeback'),
               str(ROOT / 'tools/special_disc/export')]
from build_text_candidate import read_member, file_sha, write_json
from migrate_slps_text import encoding_tables
from export_sd_text import qa_lines
from srwz.iso9660 import scan_iso9660, member_map
from srwz.codec import decode_production
from srwz.nisv_strategy_qa import QA_METADATA_GROUPS
from srwz.text import decode_text
from special_disc.source import CURRENT_ISO, SOURCE_ISO
from special_disc.writeback.qa_layout import MEMBER, page, require, sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    receipt = json.loads(CURRENT_ISO.with_suffix('.json').read_text())
    require(file_sha(CURRENT_ISO) == receipt['iso']['sha256'], 'SP ISO/receipt mismatch')
    chunks = []
    for iso in (SOURCE_ISO, CURRENT_ISO):
        members = member_map(scan_iso9660(iso))
        exe = read_member(iso, members, 'SLPS_259.20')
        archive = read_member(iso, members, MEMBER)
        a, b = struct.unpack_from('<II', exe, 0x384A00 + 24)
        chunks.append(decode_production(archive[a:b]).output)
    sp, current = chunks
    config = json.loads((ROOT / 'config/full-story-components.json').read_text())['nisv_strategy_qa']
    original_archive = (ROOT / config['original_archive']['path']).read_bytes()
    require(sha(original_archive) == config['original_archive']['sha256'], 'Original archive lock mismatch')
    target = config['target']
    original = decode_production(original_archive[target['stored_start']:target['stored_end']]).output
    native_path = ROOT / 'corpus/zh/special-disc/native-text.json'
    native = {r['id']: r for r in json.loads(native_path.read_text())['entries']}
    table, _, _, runtime = encoding_tables(ROOT / 'work/build/special-disc/text-candidate/font/proposal.json')
    pending = []

    def entry(id_, source, old, unchanged):
        row = native.get(id_)
        require(row is not None and row['source_text'] == source and
                row['source_text_sha256'] == sha(source.encode()), f'Q&A reviewed source mismatch: {id_}')
        pending.append(dict(id=id_,source_sha256=sha(source.encode()),
            editorial_status=row['editorial_status'],translation_present=bool(row['translation']),
            writeback_status=row['writeback_status'],current_equals_sp_japanese=unchanged,
            source_diff=[dict(operation=tag,original=old[i:j],sp=source[k:l])
                         for tag,i,j,k,l in difflib.SequenceMatcher(a=old,b=source,autojunk=False).get_opcodes()
                         if tag!='equal']))

    changed_pages = []
    for number in range(1, 103):
        og, jp, now = [page(chunk, number) for chunk in (original, sp, current)]
        old_blob = original[og['start']:og['start']+og['size']]
        jp_blob = sp[jp['start']:jp['start']+jp['size']]
        if old_blob != jp_blob:
            changed_pages.append(number)
            text = lambda p: qa_lines([(r['y'],decode_text(r['raw']+b'\0',0,table).text) for r in p['records']])
            entry(f'sd/nisv/qa/page/{number:03d}', text(jp), text(og),
                  [r['raw'] for r in jp['records']] == [r['raw'] for r in now['records']])
    def metadata(chunk):
        cursor = 0x476
        for group, count in QA_METADATA_GROUPS:
            for index in range(count):
                end = chunk.index(0, cursor)
                yield group, index, chunk[cursor:end]
                cursor = end+1
    changed_metadata = []
    for (group, index, old), (_, _, jp), (_, _, now) in zip(metadata(original), metadata(sp), metadata(current)):
        if old != jp:
            id_ = f'sd/nisv/qa/metadata/{group}/{index:03d}'
            changed_metadata.append(id_)
            entry(id_, decode_text(jp+b'\0',0,table).text, decode_text(old+b'\0',0,table).text, jp == now)
    rows = []
    for r in page(current, 12)['records']:
        rows.append(dict(x=r['x'],y=r['y'],style=[r['style0'],r['style1']],
                         text=decode_text(r['raw']+b'\0',0,runtime).text))
    report = dict(iso=receipt['iso'],original_archive=config['original_archive'],
        reviewed_corpus=dict(path=str(native_path.relative_to(ROOT)),sha256=file_sha(native_path)),
        page_count=102,original_identical_pages=102-len(changed_pages),changed_pages=changed_pages,
        metadata_count=264,changed_metadata=changed_metadata,
        reviewed_translation_count=sum(r['editorial_status']=='reviewed' and r['translation_present'] for r in pending),
        missing_translation_ids=[r['id'] for r in pending if not r['translation_present']],
        current_japanese_count=sum(r['current_equals_sp_japanese'] for r in pending),
        entries=pending,page_12_readback=rows,runtime='not_tested')
    write_json(args.output,report)
    print(json.dumps({k:v for k,v in report.items() if k not in ('entries','page_12_readback','changed_metadata')},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
