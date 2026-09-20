"""Independently prove the seven review-package false positives are jump entries.

Read the locked original EXE and the current ISO, check the real MIPS
LUI/SLL/ADDIU/ADDU/LW/JR consumer, and simulate indexed loads for each entry.
No ISO or corpus mutation. The JSON report keeps the byte/address evidence.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/special_disc/export')]
import export_sd_text as sd
from special_disc.writeback.exe_data_guard import NON_TEXT_WORDS
from srwz.iso9660 import scan_iso9660, member_map

OUT = ROOT / 'work/authoring/special-disc/review-imports/20260919-gpt6-pro/exe-non-text-audit.json'


def need(ok, message):
    if not ok:
        raise ValueError(message)


def verify_dispatch(data, site, table_offset, index, bias):
    words = struct.unpack_from('<6I', data, site)
    a, b, c, d, e, f = words
    op = lambda w: w >> 26
    rs = lambda w: (w >> 21) & 31
    rt = lambda w: (w >> 16) & 31
    rd = lambda w: (w >> 11) & 31
    reg_base, reg_index = rt(a), rd(b)
    need(op(a) == 15 and rs(a) == 0, 'expected LUI')
    need(op(b) == 0 and (b & 63) == 0 and ((b >> 6) & 31) == 2 and rs(b) == 0, 'expected SLL index, 2')
    need(op(c) == 9 and rs(c) == reg_base and rt(c) == reg_base, 'expected ADDIU table base')
    low = c & 65535
    low = low - 65536 if low >= 32768 else low
    base = ((a & 65535) << 16) + low
    need(base == table_offset + bias, 'table base drift')
    need(op(d) == 0 and (d & 63) == 33 and rs(d) == reg_index and rt(d) == reg_base and rd(d) == reg_index, 'expected ADDU index, base')
    need(op(e) == 35 and rs(e) == reg_index and rt(e) == reg_index and (e & 65535) == 0, 'expected LW target, 0(index)')
    need(op(f) == 0 and (f & 0x1FFFFF) == 8 and rs(f) == reg_index, 'expected JR loaded target')
    address = base + (index << 2)
    target = struct.unpack_from('<I', data, address - bias)[0]
    return dict(file_offset=f'0x{site:X}', virtual_address=f'0x{site+bias:X}',
                words=[f'0x{w:08X}' for w in words], table_virtual_address=f'0x{base:X}',
                index=index, loaded_word_offset=f'0x{address-bias:X}', jump_target=f'0x{target:X}',
                operations=['lui table_hi', 'sll index, 2', 'addiu table_lo', 'addu indexed_table', 'lw target', 'jr target'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=OUT)
    args = parser.parse_args()
    data = sd.Disc().original(sd.EXE)
    phoff = struct.unpack_from('<I', data, 28)[0]
    phsize, phcount = struct.unpack_from('<HH', data, 42)
    segments = [struct.unpack_from('<8I', data, phoff+i*phsize) for i in range(phcount)]
    seg = next(p for p in segments if p[0] == 1 and p[4] and p[1] <= min(NON_TEXT_WORDS) < p[1]+p[4])
    bias = seg[2] - seg[1]
    iso = ROOT / 'build/iso/special-disc/full-text/sp-zh-full-text.iso'
    member = member_map(scan_iso9660(iso))[sd.EXE]
    with iso.open('rb') as f:
        f.seek(member.extent_lba*2048)
        current = f.read(member.size)
    ledger = json.loads((ROOT/'corpus/zh/special-disc/reviewed-non-stage-text.json').read_text())['entries']
    sources = {r['id']:r for r in ledger}
    rows = []
    for offset, (target, table, consumer) in NON_TEXT_WORDS.items():
        raw = data[offset:offset+4]
        need(struct.unpack('<I', raw)[0] == target, 'pointer preimage drift')
        need(raw == current[offset:offset+4], 'current ISO pointer was modified')
        need(seg[2] <= target < seg[2]+seg[4], 'target outside loaded original executable')
        index = (offset-table)//4
        dispatch = verify_dispatch(data, consumer, table, index, bias)
        need(dispatch['jump_target'] == f'0x{target:X}', 'dispatch target mismatch')
        id_ = f'sd/exe/{offset:06X}'
        rows.append(dict(id=id_,false_text=sources[id_]['source_text'],classification='mips_jump_table_entry',
                         raw_hex=raw.hex(),target_virtual_address=f'0x{target:X}',target_file_offset=f'0x{target-bias:X}',
                         target_first_16_bytes=data[target-bias:target-bias+16].hex(),dispatch=dispatch,
                         current_iso_bytes_unchanged=True,writeback='excluded'))
    report = dict(status='verified_non_text',original_exe_sha256=hashlib.sha256(data).hexdigest(),
                  current_exe_sha256=hashlib.sha256(current).hexdigest(),current_iso=str(iso.relative_to(ROOT)),
                  evidence='Original bytes plus indexed MIPS load and indirect jump; no runtime claim.',entries=rows)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(status=report['status'],excluded=len(rows),current_iso_words_preserved=True)))


if __name__ == '__main__':
    main()
