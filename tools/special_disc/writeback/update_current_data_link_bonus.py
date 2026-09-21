"""Apply the default Z bonus policy to the current SP ISO without rebuilding other work."""
from pathlib import Path
import copy
import shutil
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT/'tools'), str(Path(__file__).resolve().parent)]
from build_text_candidate import load, file_sha, sha, read_member, write_json, verify_iso_ranges, require
from special_disc.source import CURRENT_ISO
from special_disc.writeback.data_link_bonus import apply_data_link_bonus, verify_data_link_bonus, SITES, DELTA, HINTS
from migrate_slps_text import encoding_tables
from srwz.iso9660 import member_map, scan_iso9660

OUTPUT = ROOT/'work/verification/sp-default-z-bonus-20260920'
EXE, VT1 = 'SLPS_259.20', 'DATA/VT1.BIN'


def main():
    path = CURRENT_ISO.with_suffix('.json'); manifest = load(path)
    require(file_sha(CURRENT_ISO) == manifest['iso']['sha256'], 'current ISO identity drift')
    members = member_map(scan_iso9660(CURRENT_ISO))
    before = {n: read_member(CURRENT_ISO, members, n) for n in (EXE, VT1)}
    for n, data in before.items():
        require(sha(data) == manifest['files'][n], f'current {n} identity drift')
    proposal = ROOT/'work/build/special-disc/text-candidate/font/proposal.json'
    require(file_sha(proposal) == manifest['proposal_sha256'], 'current font proposal drift')
    table, _, codes, readback = encoding_tables(proposal)
    exe, vt1, policy = apply_data_link_bonus(before[EXE], before[VT1], table, codes, readback)
    after = {EXE: exe, VT1: vt1}
    if after == before:
        print('SP default Z dual-route policy already applied and verified')
        return
    OUTPUT.mkdir(parents=True, exist_ok=True)
    write_json(OUTPUT/'previous-manifest.json', manifest)
    for n in (EXE,):
        (OUTPUT/('before-'+n)).write_bytes(before[n])
    temporary = CURRENT_ISO.with_suffix('.tmp.iso')
    require(not temporary.exists(), 'another current ISO update is in progress')
    try:
        shutil.copyfile(CURRENT_ISO, temporary)
        with temporary.open('r+b') as f:
            for n, data in after.items():
                require(len(data) == members[n].size, f'{n} size changed')
                f.seek(members[n].extent_lba*2048); f.write(data)
        layout = member_map(scan_iso9660(temporary))
        require({n: (m.extent_lba, m.size) for n, m in members.items()} ==
                {n: (m.extent_lba, m.size) for n, m in layout.items()}, 'ISO layout changed')
        actual = {n: read_member(temporary, layout, n) for n in after}
        require(actual == after, 'default Z bonus ISO readback mismatch')
        verify_data_link_bonus(actual[EXE], actual[VT1], readback)
        base = members[EXE].extent_lba*2048
        ranges = [(base+va-DELTA, base+va-DELTA+len(new)) for va, _, new in SITES]
        ranges.extend((base+at, base+at+size) for at, size, _ in HINTS)
        base = members[VT1].extent_lba*2048
        ranges.append(tuple(base+x for x in policy['vt1_range']))
        protected = verify_iso_ranges(CURRENT_ISO, temporary, ranges)
        receipt = dict(status='default_z_bonus_static_and_iso_readback_passed_runtime_pending',
                       previous_iso=manifest['iso'], data_link_bonus=policy,
                       protected_iso_ranges=protected, member_layout_preserved=True,
                       iso=dict(path=str(CURRENT_ISO.relative_to(ROOT)), size=temporary.stat().st_size,
                                sha256=file_sha(temporary)))
        updated = copy.deepcopy(manifest)
        updated.update(iso=receipt['iso'], data_link_bonus=policy,
                       status=receipt['status'], runtime='pending after default Z bonus policy')
        for n, data in after.items():
            updated['files'][n] = sha(data)
        updated['data_link_bonus_update'] = dict(receipt=str((OUTPUT/'readback.json').relative_to(ROOT)),
            previous_manifest=str((OUTPUT/'previous-manifest.json').relative_to(ROOT)))
        for p in (Path(__file__), ROOT/'tools/special_disc/writeback/data_link_bonus.py',
                  ROOT/'tools/special_disc/writeback/build_full_text.py'):
            updated['source_files'][str(p.relative_to(ROOT))] = file_sha(p)
        require(file_sha(CURRENT_ISO) == manifest['iso']['sha256'] and load(path) == manifest,
                'current ISO/manifest changed during update')
        temporary.replace(CURRENT_ISO)
        write_json(path, updated); write_json(OUTPUT/'readback.json', receipt)
        print(receipt['iso'])
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
