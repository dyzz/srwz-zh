"""Install the guarded keyword-list repair in the current SP ISO."""
from pathlib import Path
import copy
import shutil
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT/'tools'), str(Path(__file__).resolve().parent)]
from build_text_candidate import load, file_sha, read_member, write_json, verify_iso_ranges
from migrate_slps_text import encoding_tables
from special_disc.source import CURRENT_ISO
from special_disc.writeback.keyword_list_names import apply_keyword_names, verify_keyword_names, MEMBER, require, sha
from srwz.iso9660 import member_map, scan_iso9660

OUTPUT = ROOT/'work/verification/sp-current-keyword-list-names'
PROPOSAL = ROOT/'work/build/special-disc/text-candidate/font/proposal.json'


def main():
    manifest_path = CURRENT_ISO.with_suffix('.json')
    manifest_bytes = manifest_path.read_bytes()
    manifest = load(manifest_path)
    require(file_sha(CURRENT_ISO) == manifest['iso']['sha256'], 'current ISO identity drift')
    require(file_sha(PROPOSAL) == manifest['proposal_sha256'], 'current font proposal drift')
    members = member_map(scan_iso9660(CURRENT_ISO))
    before = read_member(CURRENT_ISO, members, MEMBER)
    require(sha(before) == manifest['files'][MEMBER], 'current COMPDATA identity drift')
    table, _, overrides, readback = encoding_tables(PROPOSAL)
    result, names = apply_keyword_names(before, table, overrides, readback)
    if result == before:
        print('all SP keyword-list names already match the approved corpus')
        return
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT/'previous-manifest.json').write_bytes(manifest_bytes)
    (OUTPUT/'previous-COMPDATA.BN').write_bytes(before)
    temporary = CURRENT_ISO.with_suffix('.tmp.iso')
    require(not temporary.exists(), 'another current ISO update is in progress')
    try:
        shutil.copyfile(CURRENT_ISO, temporary)
        at = members[MEMBER].extent_lba*2048
        with temporary.open('r+b') as stream:
            stream.seek(at)
            stream.write(result)
        after = member_map(scan_iso9660(temporary))
        require({n:(m.extent_lba,m.size) for n,m in members.items()} ==
                {n:(m.extent_lba,m.size) for n,m in after.items()}, 'ISO layout changed')
        actual = read_member(temporary, after, MEMBER)
        require(actual == result, 'keyword-list ISO member readback failed')
        verify_keyword_names(actual, readback)
        protected = verify_iso_ranges(CURRENT_ISO, temporary, [(at, at+len(result))])
        receipt = dict(status='keyword_list_static_verified_runtime_pending', previous_iso=manifest['iso'],
            keyword_list_names=names, protected_iso_ranges=protected, member_sha256=sha(result),
            iso=dict(path=str(CURRENT_ISO.relative_to(ROOT)), size=temporary.stat().st_size,
                     sha256=file_sha(temporary)))
        updated = copy.deepcopy(manifest)
        updated.update(iso=receipt['iso'], status=receipt['status'], keyword_list_names=names)
        updated['files'][MEMBER] = sha(result)
        updated['keyword_list_update'] = dict(receipt=str((OUTPUT/'readback.json').relative_to(ROOT)),
            previous_manifest=str((OUTPUT/'previous-manifest.json').relative_to(ROOT)))
        updated['coverage']['repaired_keyword_list_names'] = 5
        # Preserve historical build-source hashes; record this incremental repair separately.
        receipt['source_files'] = {str(p.relative_to(ROOT)):file_sha(p) for p in
            [Path(__file__), ROOT/'tools/special_disc/writeback/keyword_list_names.py']}
        require(file_sha(CURRENT_ISO) == manifest['iso']['sha256'] and
                manifest_path.read_bytes() == manifest_bytes, 'current ISO/manifest changed during update')
        temporary.replace(CURRENT_ISO)
        write_json(manifest_path, updated)
        write_json(OUTPUT/'readback.json', receipt)
        print(receipt['iso'])
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
