"""Verify all Q&A allocations and reviewed text from the current SP ISO."""
from pathlib import Path
import argparse
import json
import re
import struct
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'tools/special_disc/writeback')]
from build_text_candidate import read_member, file_sha, write_json
from migrate_slps_text import encoding_tables
from special_disc.source import CURRENT_ISO, SOURCE_ISO
from special_disc.writeback.qa_layout import page, require, sha, compile_original
from special_disc.writeback.qa_native import metadata, shared_records, styled_runs, validate_records, MAX_X
from srwz.iso9660 import scan_iso9660, member_map
from srwz.codec import decode_production
from srwz.text import decode_text, two_byte_visible_spaces

KANA = re.compile(r'[\u3041-\u3096\u309d-\u309f\u30a1-\u30fa\u30fd-\u30ff\uff66-\uff9f]')
TOKEN = re.compile(r'[A-Za-z0-9]+(?:[.．][0-9]+)*(?:[%％]|倍|点|级|段|机|格|回合|人|种|个|次|型|键)?')
INDEPENDENT_ITEMS = {(36,'S5个'),(37,'SABCD点'),(43,'SABCD点'),(83,'2MAP')}


def verify():
    receipt_bytes = CURRENT_ISO.with_suffix('.json').read_bytes()
    receipt = json.loads(receipt_bytes)
    require(file_sha(CURRENT_ISO) == receipt['iso']['sha256'], 'SP ISO/receipt drift')
    chunks = []
    for iso in (SOURCE_ISO,CURRENT_ISO):
        members = member_map(scan_iso9660(iso))
        exe = read_member(iso,members,'SLPS_259.20')
        data = read_member(iso,members,'DATA/NISVDATA.BIN')
        a,b = struct.unpack_from('<II',exe,0x384A00+24)
        chunks.append(decode_production(data[a:b]).output)
    source,current = chunks
    T,_,O,R = encoding_tables(ROOT/'work/build/special-disc/text-candidate/font/proposal.json')
    _,original,_ = compile_original(T,O)
    native = {e['id']:e for e in json.loads((ROOT/'corpus/zh/special-disc/native-text.json').read_text())['entries']}
    require(current[:0x476] == source[:0x476], 'Q&A allocation table/metadata indexes changed')
    reviewed,records,padding = [],0,[]
    independent_items = []
    for n in range(1,103):
        parsed,jp = page(current,n),page(source,n)
        require(parsed['size'] == jp['size'] and parsed['start'] == jp['start'] and
                parsed['sprite_bytes'] == jp['sprite_bytes'], 'Q&A allocation/sprite drift')
        rs = shared_records(parsed,R)
        validate_records(rs)
        text = ''.join(r['text'] for r in rs)
        ys = [r['position'][1] for r in rs for _ in r['text']]
        for match in TOKEN.finditer(text):
            if len(set(ys[match.start():match.end()])) > 1:
                require((n,match.group()) in INDEPENDENT_ITEMS, f'Q&A split numeric/Latin token: {n} {match.group()}')
                independent_items.append(dict(page=n,token=match.group(),reason='separate table/list/paragraph items'))
        require(not KANA.search(text), f'Q&A kana remains: {n}')
        for r in parsed['records']:
            require(len(r['raw']) % 2 == 0 and b'\x20' not in r['raw'], 'Q&A stream alignment drift')
        ident = f'sd/nisv/qa/page/{n:03d}'
        if ident in native:
            require(text == two_byte_visible_spaces(native[ident]['translation'].replace('\n','')),
                    f'Reviewed Q&A text mismatch: {n}')
            reviewed.append(ident)
        else:
            require(styled_runs(rs) == styled_runs(shared_records(page(original,n),R)),
                    f'Shared Q&A styled text mismatch: {n}')
        records += len(rs)
        padding.append(parsed['padding_size'])
    for (group,index,raw),(_,_,og) in zip(metadata(current),metadata(original)):
        text = decode_text(raw+b'\0',0,R).text
        require(not KANA.search(text) and b'\x20' not in raw, 'Q&A metadata kana/space drift')
        ident = f'sd/nisv/qa/metadata/{group}/{index:03d}'
        if ident in native:
            require(text == two_byte_visible_spaces(native[ident]['translation']), f'Metadata mismatch: {ident}')
            reviewed.append(ident)
        else:
            require(raw == og, f'Shared metadata drift: {ident}')
    require(len(reviewed) == 37, 'Reviewed Q&A coverage drift')
    require(CURRENT_ISO.with_suffix('.json').read_bytes() == receipt_bytes, 'Concurrent SP receipt change')
    q = receipt['qa_layout']
    return dict(iso=receipt['iso'], page_count=102, metadata_count=264, record_count=records,
        reviewed_text_exact=reviewed, shared_styled_text_exact=True, all_layout_bounds_passed=True,
        kana_residue_count=0, leading_closing_punctuation_count=0, trailing_opening_punctuation_count=0,
        overlap_count=0, overflow_count=0, source_allocations_indexes_sprites_exact=True,
        maximum_visible_glyph_x=MAX_X,
        numeric_split_count=0, numeric_scan_false_positives=independent_items,
        visible_space_encoding='0x8140', minimum_page_padding=min(padding),
        decoded_sha256=sha(current), compressed_bytes=q.get('stored_size'), compressed_budget=b-a,
        shared_repair_pages=[e['page'] for e in q['shared_layout_repairs']],
        shared_repair_count=sum(len(e['repairs']) for e in q['shared_layout_repairs']),
        native_pages=q['native_pages'], protected_iso_ranges=receipt['qa_layout_update']['protected_iso_ranges'],
        runtime='separate LRPS2 evidence; static verification only')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    args = p.parse_args()
    result = verify()
    write_json(args.output,result)
    print(json.dumps({k:v for k,v in result.items() if k != 'reviewed_text_exact'},ensure_ascii=False,indent=2))
