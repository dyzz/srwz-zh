"""Verify or atomically update the title images in the single SP current ISO."""
from pathlib import Path
import argparse
import json
import shutil
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT/'tools'), str(Path(__file__).resolve().parent)]
from build_text_candidate import read_member, file_sha, verify_iso_ranges, write_json
from srwz.iso9660 import scan_iso9660, member_map
from srwz.codec import decode_production
from special_disc.writeback.stage_titles import (apply_stage_titles, verify_stage_titles,
    verify_title_bindings, MEMBER, require, sha)
from special_disc.source import CURRENT_ISO


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, default=CURRENT_ISO)
    parser.add_argument('--output', type=Path, default=CURRENT_ISO)
    args = parser.parse_args()
    members = member_map(scan_iso9660(args.base))
    exe = read_member(args.base, members, 'SLPS_259.20')
    verify_title_bindings(decode_production(read_member(args.base, members, 'DATA/COMPDATA.BN')).output)
    original = read_member(args.base, members, MEMBER)
    if args.base.resolve() == args.output.resolve():
        try:
            verify_stage_titles(original, exe)
        except ValueError:
            pass
        else:
            print('sp-current.iso already contains all verified stage-title slots')
            return
    baseline_sha = file_sha(args.base)
    output, titles = apply_stage_titles(original, exe)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix('.tmp.iso')
    shutil.copyfile(args.base, temporary)
    at = members[MEMBER].extent_lba * 2048
    with temporary.open('r+b') as stream:
        stream.seek(at); stream.write(output)
    after = member_map(scan_iso9660(temporary))
    require({n:(m.extent_lba,m.size) for n,m in members.items()} ==
            {n:(m.extent_lba,m.size) for n,m in after.items()}, 'title candidate ISO layout drift')
    actual = read_member(temporary, after, MEMBER)
    require(actual == output, 'title candidate ISO member readback failed')
    verify_stage_titles(actual, exe)
    from special_disc.writeback.stage_titles import inputs
    _, offsets, group_start, group_end = inputs(exe)
    protected = verify_iso_ranges(args.base, temporary,
        [(at+group_start+offsets[6], at+group_end)])
    temporary.replace(args.output)
    report = dict(status='title_only_static_verified_runtime_pending',
        iso=dict(path=str(args.output.resolve().relative_to(ROOT)), size=args.output.stat().st_size,
                 sha256=file_sha(args.output)),
        baseline=dict(path=str(args.base.resolve().relative_to(ROOT)), sha256=baseline_sha),
        stage_titles=titles, protected_iso_ranges=protected,
        member_sha256=sha(output), runtime='pending')
    write_json(args.output.with_suffix('.json'), report)
    print(json.dumps(report['iso'], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
