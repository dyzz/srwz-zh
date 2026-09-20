"""Atomically install paired frozen title resources into the current SP ISO.

Unrelated current-disc updates are retained. This incremental build is useful
when historical full-build components have a different font/codebook identity.
"""
from pathlib import Path
import argparse
import json
import shutil
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'tools'), str(Path(__file__).resolve().parent)]
from build_text_candidate import read_member, file_sha, verify_iso_ranges, write_json
from srwz.iso9660 import scan_iso9660, member_map
from special_disc.source import CURRENT_ISO
from special_disc.writeback.command_headings import apply_command_headings, CONFIG as COMMAND_CONFIG, KVM, KVP
from special_disc.writeback.title_atlas import apply_title_atlas, CONFIG, require, sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-receipt', type=Path)
    args = parser.parse_args()
    receipt_path = CURRENT_ISO.with_suffix('.json')
    receipt_bytes = receipt_path.read_bytes()
    receipt = json.loads(receipt_bytes)
    baseline_sha = file_sha(CURRENT_ISO)
    require(baseline_sha == receipt['iso']['sha256'], 'SP current ISO/receipt drift')
    members = member_map(scan_iso9660(CURRENT_ISO))
    original = {n: read_member(CURRENT_ISO, members, n) for n in (KVM, KVP)}
    atlas, drawings, command_report = apply_command_headings(original[KVM], original[KVP])
    atlas, drawings, report = apply_title_atlas(atlas, drawings)
    outputs = {KVM: atlas, KVP: drawings}
    evidence = None
    if args.runtime_receipt:
        runtime = json.loads(args.runtime_receipt.read_text())
        contract = json.loads(Path(runtime['iso']['build_config']).read_text())
        require(runtime['status'] == 'passed' and runtime['iso']['sha256'] == contract['output']['expected_sha256'],
                'SP title runtime receipt/ISO identity mismatch')
        require(report['files'] == contract['title_atlas']['files'] and
                report['config_sha256'] == contract['title_atlas']['config_sha256'],
                'SP title runtime evidence does not match frozen title resources')
        evidence = dict(path=str(args.runtime_receipt.resolve().relative_to(ROOT)), sha256=file_sha(args.runtime_receipt),
                        tested_iso_sha256=runtime['iso']['sha256'],
                        scope='LRPS2 natural challenge/help/support flow; other title scenes and PCSX2 pending',
                        same_title_resources=True, current_iso_may_include_other_updates=True)
    if outputs == original:
        print('SP current ISO already contains the frozen title atlas')
        return
    temporary = CURRENT_ISO.with_suffix('.title-atlas.tmp.iso')
    require(not temporary.exists(), 'SP title temporary ISO already exists')
    out = ROOT / 'work/build/special-disc/title-atlas'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'previous-current-receipt.json').write_bytes(receipt_bytes)
    try:
        shutil.copyfile(CURRENT_ISO, temporary)
        with temporary.open('r+b') as stream:
            for name, data in outputs.items():
                require(len(data) == members[name].size, 'SP title member size changed')
                stream.seek(members[name].extent_lba * 2048); stream.write(data)
        after = member_map(scan_iso9660(temporary))
        require({n:(m.extent_lba,m.size) for n,m in members.items()} ==
                {n:(m.extent_lba,m.size) for n,m in after.items()}, 'SP title ISO layout drift')
        for name, data in outputs.items():
            require(read_member(temporary, after, name) == data, 'SP title ISO readback mismatch')
        protected = verify_iso_ranges(CURRENT_ISO, temporary,
            [(members[n].extent_lba*2048, members[n].extent_lba*2048+len(data)) for n,data in outputs.items()])
        output_sha = file_sha(temporary)
        require(file_sha(CURRENT_ISO) == baseline_sha and receipt_path.read_bytes() == receipt_bytes,
                'SP current changed during title build; refusing to replace concurrent work')
        require(file_sha(CONFIG) == report['config_sha256'] and file_sha(COMMAND_CONFIG) == command_report['config_sha256'],
                'SP title configuration changed during build')
        receipt['iso']['sha256'] = output_sha
        receipt['files'].update(report['files'])
        receipt['title_atlas'], receipt['command_headings'] = report, command_report
        receipt['title_atlas_update'] = dict(baseline_sha256=baseline_sha, protected_iso_ranges=protected,
            runtime_evidence=evidence, method='paired_resource_incremental_overlay')
        receipt['status'] = 'sp_titles_static_verified_runtime_partial'
        receipt['runtime'] = 'partial_title_coverage_other_routes_pending'
        for name in ('title_atlas.py', 'command_headings.py', 'build_title_atlas_candidate.py'):
            path = Path(__file__).parent / name
            receipt.setdefault('source_files', {})[str(path.relative_to(ROOT))] = file_sha(path)
        temporary.replace(CURRENT_ISO)
        write_json(receipt_path, receipt)
        write_json(out / 'promotion.json', dict(iso=receipt['iso'],title_atlas=report,update=receipt['title_atlas_update']))
        print(json.dumps(dict(iso=receipt['iso'],title_atlas=report), ensure_ascii=False, indent=2))
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
