"""Compare ordered native controls in original/final SP COMPDATA strings.

Run from a project checkout: python3 <this script> --iso ISO --proposal JSON.
The proposal must be the exact SP build's font proposal. No runtime claim.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'tools/srwz/text.py').is_file())
sys.path.insert(0, str(ROOT / 'tools'))
from srwz.iso9660 import member_map, scan_iso9660
from srwz.codec import decode_production
from srwz.text import decode_text, runtime_control_bytes, verify_runtime_control_bytes
from special_disc.writeback.migrate_slps_text import encoding_tables


def member(iso):
    entries = member_map(scan_iso9660(iso))
    row = entries['DATA/COMPDATA.BN']
    with iso.open('rb') as f:
        f.seek(row.extent_lba * 2048)
        return decode_production(f.read(row.size)).output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iso', type=Path, required=True)
    parser.add_argument('--proposal', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = ROOT / 'rom/Super Robot Taisen Z - Special Disc [J].iso'
    original, final = member(source), member(args.iso)
    table, _, _, readback = encoding_tables(args.proposal)
    rows = []
    for row in json.loads((ROOT / 'corpus/zh/special-disc/system-text.json').read_text())['entries']:
        if not row['id'].startswith('sd/compdata/'):
            continue
        expected = runtime_control_bytes(row['translation'])
        if not expected:
            continue
        offset = int(row['id'].rsplit('/', 1)[1], 16)
        # These explicit native-control fields remain at their original fixed slots.
        native = decode_text(original, offset, table)
        actual = decode_text(final, offset, readback)
        assert native.text == row['source_text'], row['id']
        source_controls = verify_runtime_control_bytes(original[offset:native.end], table, native.text)
        assert source_controls == expected, (row['id'], 'source/translation contract')
        try:
            controls = verify_runtime_control_bytes(final[offset:actual.end], readback, row['translation'])
            error = None
        except ValueError as exc:
            controls, error = (), str(exc)
        rows.append(dict(id=row['id'], offset=offset,
                         native_controls=[x.hex() for x in source_controls],
                         final_controls=[x.hex() for x in controls], error=error))
    result = dict(scope='SP fixed COMPDATA native controls; raw bytes independently checked; no runtime claim',
                  iso=str(args.iso), proposal=str(args.proposal),
                  decoded_member_sha256=hashlib.sha256(final).hexdigest(),
                  entries=len(rows), native_controls=sum(len(x['native_controls']) for x in rows),
                  failures=sum(x['error'] is not None for x in rows), rows=rows)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'rows'}, indent=2))
    return 1 if result['failures'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
