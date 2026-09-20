"""Atomically write reviewed native and shared Q&A into the current SP ISO."""
from pathlib import Path
import json
import shutil
import struct
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'tools'), str(Path(__file__).resolve().parent)]
from build_text_candidate import read_member, file_sha, verify_iso_ranges, write_json
from migrate_slps_text import encoding_tables
from srwz.iso9660 import scan_iso9660, member_map
from special_disc.source import CURRENT_ISO, SOURCE_ISO
from special_disc.writeback.qa_layout import MEMBER, require, sha
from special_disc.writeback.qa_native import apply_reviewed_qa


def main():
    receipt_path = CURRENT_ISO.with_suffix('.json')
    receipt_bytes = receipt_path.read_bytes()
    receipt = json.loads(receipt_bytes)
    baseline_sha = file_sha(CURRENT_ISO)
    require(baseline_sha == receipt['iso']['sha256'], 'SP current ISO/receipt drift')
    members = member_map(scan_iso9660(CURRENT_ISO))
    exe = read_member(CURRENT_ISO, members, 'SLPS_259.20')
    original = read_member(CURRENT_ISO, members, MEMBER)
    source = read_member(SOURCE_ISO, member_map(scan_iso9660(SOURCE_ISO)), MEMBER)
    proposal = ROOT / 'work/build/special-disc/text-candidate/font/proposal.json'
    table, _, overrides, _ = encoding_tables(proposal)
    output, report = apply_reviewed_qa(original, exe, source, table, overrides)
    if output == original:
        print('SP current ISO already contains the reviewed Q&A layout')
        return
    temporary = CURRENT_ISO.with_suffix('.qa-layout.tmp.iso')
    require(not temporary.exists(), 'Q&A temporary ISO already exists')
    try:
        shutil.copyfile(CURRENT_ISO, temporary)
        at = members[MEMBER].extent_lba * 2048
        with temporary.open('r+b') as stream:
            stream.seek(at)
            stream.write(output)
        after = member_map(scan_iso9660(temporary))
        require({n: (m.extent_lba, m.size) for n, m in members.items()} ==
                {n: (m.extent_lba, m.size) for n, m in after.items()}, 'SP ISO layout drift')
        require(read_member(temporary, after, MEMBER) == output, 'SP Q&A ISO readback mismatch')
        a, b = struct.unpack_from('<II', exe, 0x384A00 + 6 * 4)
        protected = verify_iso_ranges(CURRENT_ISO, temporary, [(at+a, at+b)])
        output_sha = file_sha(temporary)
        require(file_sha(CURRENT_ISO) == baseline_sha and receipt_path.read_bytes() == receipt_bytes,
                'SP current changed during Q&A build; refusing to replace concurrent work')
        receipt['iso']['sha256'] = output_sha
        receipt['files'][MEMBER] = sha(output)
        receipt['qa_layout'] = report
        receipt['qa_layout_update'] = dict(baseline_sha256=baseline_sha,
            protected_iso_ranges=protected, proposal_sha256=file_sha(proposal))
        receipt['runtime'] = 'pending'
        for name in ('qa_layout.py', 'qa_native.py', 'build_qa_layout_candidate.py'):
            path = Path(__file__).parent / name
            receipt.setdefault('source_files', {})[str(path.relative_to(ROOT))] = file_sha(path)
        temporary.replace(CURRENT_ISO)
        write_json(receipt_path, receipt)
        print(json.dumps(dict(iso=receipt['iso'], qa_layout=report), ensure_ascii=False, indent=2))
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
