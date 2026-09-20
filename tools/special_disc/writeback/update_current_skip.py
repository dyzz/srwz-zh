"""Atomically add the locked SP square-skip hook, preserving every other ISO byte."""
from pathlib import Path
import copy
import json
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT/'tools'), str(Path(__file__).resolve().parent)]
from build_text_candidate import load, file_sha, sha, read_member, write_json, verify_iso_ranges, require
from special_disc.source import CURRENT_ISO
from special_disc.writeback.battle_square_skip import apply_skip, verify_skip, load_contract, CONTRACT
from srwz.battle_square_skip import executable_write_ranges
from srwz.iso9660 import member_map, scan_iso9660

OUTPUT = ROOT/'work/verification/sp-square-skip-20260920'
EXE = 'SLPS_259.20'


def main():
    manifest_path = CURRENT_ISO.with_suffix('.json')
    manifest = load(manifest_path)
    require(file_sha(CURRENT_ISO) == manifest['iso']['sha256'], 'current ISO identity drift')
    members = member_map(scan_iso9660(CURRENT_ISO))
    before = read_member(CURRENT_ISO, members, EXE)
    require(sha(before) == manifest['files'][EXE], 'current executable identity drift')
    after, policy = apply_skip(before)
    if after == before:
        verify_skip(before)
        print('SP square skip already installed and verified')
        return
    OUTPUT.mkdir(parents=True, exist_ok=True)
    write_json(OUTPUT/'previous-manifest.json', manifest)
    (OUTPUT/('before-'+EXE)).write_bytes(before)
    # A private filename prevents simultaneous updates from sharing a staging file.
    with tempfile.TemporaryDirectory(prefix='.skip-', dir=CURRENT_ISO.parent) as temp:
        temporary = Path(temp)/'candidate.iso'
        shutil.copyfile(CURRENT_ISO, temporary)
        row = members[EXE]
        require(len(before) == len(after) == row.size, 'executable size changed')
        with temporary.open('r+b') as stream:
            stream.seek(row.extent_lba*2048)
            stream.write(after)
        layout = member_map(scan_iso9660(temporary))
        require({n:(m.extent_lba,m.size) for n,m in members.items()} ==
                {n:(m.extent_lba,m.size) for n,m in layout.items()}, 'ISO layout changed')
        actual = read_member(temporary, layout, EXE)
        require(actual == after, 'skip executable readback mismatch')
        verified = verify_skip(actual)
        offset = row.extent_lba*2048
        ranges = [(offset+lo,offset+hi) for lo,hi in executable_write_ranges(load_contract(),'sp')]
        protected = verify_iso_ranges(CURRENT_ISO, temporary, ranges)
        receipt = dict(status='square_skip_static_and_iso_readback_passed_runtime_pending',
                       previous_iso=manifest['iso'], battle_square_skip=policy,
                       verified_hook=verified, protected_iso_ranges=protected,
                       member_layout_preserved=True, runtime='pending',
                       iso=dict(path=str(CURRENT_ISO.relative_to(ROOT)),size=temporary.stat().st_size,
                                sha256=file_sha(temporary)))
        updated = copy.deepcopy(manifest)
        updated.update(iso=receipt['iso'], battle_square_skip=policy,
                       status=receipt['status'], runtime='pending for newly added square skip')
        updated['files'][EXE] = sha(after)
        updated['square_skip_update'] = dict(receipt=str((OUTPUT/'readback.json').relative_to(ROOT)),
            previous_manifest=str((OUTPUT/'previous-manifest.json').relative_to(ROOT)))
        for path in (Path(__file__), CONTRACT, ROOT/'tools/special_disc/writeback/battle_square_skip.py',
                     ROOT/'tools/srwz/battle_square_skip.py', ROOT/'tools/native/battle-square-skip/skip_hook.s',
                     ROOT/'tools/special_disc/writeback/build_full_text.py'):
            updated['source_files'][str(path.relative_to(ROOT))] = file_sha(path)
        require(file_sha(CURRENT_ISO) == manifest['iso']['sha256'] and load(manifest_path) == manifest,
                'current ISO/manifest changed during skip update')
        write_json(Path(temp)/'candidate.json', updated)
        temporary.replace(CURRENT_ISO)
        (Path(temp)/'candidate.json').replace(manifest_path)
        write_json(OUTPUT/'readback.json', receipt)
        print(json.dumps(receipt['iso'],indent=2))


if __name__ == '__main__':
    main()
